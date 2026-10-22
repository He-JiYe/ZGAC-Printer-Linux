"""Independent implementation of the observed v5 wire representation.

Keys and per-package mixing positions are supplied by the private local profile.
Twofish is provided by the operating system's libgcrypt, never hand-written.
"""
import ctypes as C
from ctypes.util import find_library
import hashlib
import secrets
import struct

from zgcaprint.common.errors import PrintError


def signature(text, key):
    return hashlib.md5((text + '&' + key).encode('utf-8'), usedforsecurity=False).hexdigest().upper()


def twofish(data, key, decrypt=False):
    if len(data) % 16 or len(key) != 16:
        raise PrintError('Twofish 输入长度无效。')
    library = find_library('gcrypt')
    if not library:
        raise PrintError('缺少 libgcrypt20，请安装系统软件包。')
    g = C.CDLL(library)
    g.gcry_check_version.argtypes = [C.c_char_p]
    g.gcry_check_version.restype = C.c_char_p
    g.gcry_cipher_map_name.argtypes = [C.c_char_p]
    g.gcry_cipher_map_name.restype = C.c_int
    g.gcry_cipher_open.argtypes = [C.POINTER(C.c_void_p), C.c_int, C.c_int, C.c_uint]
    g.gcry_cipher_setkey.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
    g.gcry_cipher_close.argtypes = [C.c_void_p]
    for fn_name in ['gcry_cipher_encrypt', 'gcry_cipher_decrypt']:
        getattr(g, fn_name).argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t]
    g.gcry_check_version(None)
    handle = C.c_void_p()
    if g.gcry_cipher_open(C.byref(handle), g.gcry_cipher_map_name(b'TWOFISH128'), 1, 0):
        raise PrintError('系统 Twofish 算法不可用。')
    try:
        if g.gcry_cipher_setkey(handle, key, len(key)):
            raise PrintError('Twofish 密钥设置失败。')
        output = C.create_string_buffer(len(data))
        fn = g.gcry_cipher_decrypt if decrypt else g.gcry_cipher_encrypt
        if fn(handle, output, len(data), data, len(data)):
            raise PrintError('Twofish 编码失败。')
        return output.raw
    finally:
        g.gcry_cipher_close(handle)


def encode_password(password, profile, rng=None):
    raw = password.encode('utf-8')
    if b'\0' in raw or len(raw) > 240:
        raise PrintError('密码含不支持的字符或长度超过 240 字节。')
    rng = rng or secrets.SystemRandom()
    padded = max(16, (len(raw)+15)//16*16)
    positions = rng.sample(range(padded), 5)
    block = bytearray(padded+16)
    block[:len(raw)] = raw
    block[padded:padded+5] = bytes(positions)
    for i, (pos, value) in enumerate(zip(positions, b'\x05' + struct.pack('<i', -1))):
        block[padded+15-i] = block[pos]
        block[pos] = value
    encrypted = twofish(bytes(block), bytes.fromhex(profile['password_key_hex']))
    result = []
    for i, value in enumerate(encrypted):
        for mix in profile['password_mix_indices']:
            if i == mix:
                result.extend(chr(65+rng.randrange(26)) for _ in range(2))
        result += [chr(65+(value & 15)), chr(65+(value >> 4))]
    return ''.join(result)


def decode_password(encoded, profile):
    """Decode the storage credentials returned by the ordinary v5 API."""
    mix = profile['password_mix_indices']
    size = (len(encoded)-2*len(mix))//2
    if len(encoded) != size*2+2*len(mix) or size < 32 or size % 16:
        raise PrintError('服务器返回了不支持的密码编码。')
    encrypted = bytearray()
    at = 0
    for i in range(size):
        at += 2*mix.count(i)
        pair = encoded[at:at+2]
        if len(pair) != 2 or any(c < 'A' or c > 'P' for c in pair):
            raise PrintError('服务器密码编码无效。')
        encrypted.append(ord(pair[0])-65 + ((ord(pair[1])-65) << 4))
        at += 2
    block = bytearray(twofish(bytes(encrypted), bytes.fromhex(profile['password_key_hex']), True))
    padded = len(block)-16
    positions = list(block[padded:padded+5])
    if len(set(positions)) != 5 or any(x >= padded for x in positions) or block[positions[0]] != 5:
        raise PrintError('服务器密码编码校验失败。')
    for i, pos in enumerate(positions):
        block[pos] = block[padded+15-i]
    try:
        return block[:padded].split(b'\0', 1)[0].decode('utf-8')
    except UnicodeDecodeError:
        raise PrintError('服务器密码字符编码不受支持。') from None
