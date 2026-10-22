"""The first-run UI is exercised only on a private virtual display."""
import os
import time
import pytest
from zgcaprint.common.errors import PrintError

pytestmark=pytest.mark.skipif(os.environ.get('ZGCAPRINT_TEST_UI')!='1',reason='requires private virtual display')


def pump(window,condition,timeout=3):
    until=time.monotonic()+timeout
    while not condition() and time.monotonic()<until:
        window.root.update();time.sleep(0.01)
    assert condition()


def test_first_run_error_can_be_retried_without_a_terminal(tmp_path):
    from zgcaprint.ui.setup import SetupWindow
    attempts=[]
    def fake(home,**kwargs):
        attempts.append(1)
        if len(attempts)==1:raise PrintError('合成网络错误，请重试。')
    window=SetupWindow(tmp_path,provisioner=fake)
    try:
        pump(window,lambda:len(attempts)==1 and not window.busy)
        assert '合成网络错误' in window.message.get()
        assert not window.retry.instate(['disabled'])
        window.start()
        pump(window,lambda:window.success)
        assert window.closed and len(attempts)==2
    finally:
        if not window.closed:window.close()


def test_first_run_small_window_keeps_actions_visible(tmp_path):
    from zgcaprint.ui.setup import SetupWindow
    window=SetupWindow(tmp_path,provisioner=lambda *args,**kwargs:None)
    try:
        window.root.geometry('460x350');window.root.update()
        for button in [window.retry,window.local]:
            assert button.winfo_viewable()
            bottom=button.winfo_rooty()-window.root.winfo_rooty()+button.winfo_height()
            assert bottom<=window.root.winfo_height()
    finally:window.close()
