from zgcaprint.printing.automation import AutoSubmitQueue


def job(name, source='cups', state='prepared', created=1):
    return {'id': name, 'source': source, 'state': state, 'created_at': created}


def test_only_new_prepared_cups_jobs_are_eligible():
    auto = AutoSubmitQueue(['old'])
    auto.observe([job('old'), job('manual', 'manual'), job('uncertain', state='uncertain'),
                  job('sent', state='submitted'), job('new')], True)
    assert auto.take(False) is None
    assert auto.take(True) == 'new'
    assert auto.take(True) is None
    auto.finished(True)
    assert auto.take(True) is None


def test_arrivals_before_login_wait_without_being_lost():
    auto = AutoSubmitQueue()
    auto.observe([job('one'), job('two', created=2)], True)
    assert auto.take(False) is None
    assert auto.take(True, busy=True) is None
    assert auto.take(True) == 'one'
    auto.finished(True)
    assert auto.take(True) == 'two'


def test_repeated_scan_and_repeated_backend_delivery_do_not_duplicate():
    auto = AutoSubmitQueue()
    for _ in range(3): auto.observe([job('one')], True)
    assert auto.take(True) == 'one'
    auto.finished(True)
    auto.observe([job('one')], True)
    assert auto.take(True) is None


def test_failure_pauses_automation_and_never_retries():
    auto = AutoSubmitQueue()
    auto.observe([job('one'), job('two')], True)
    assert auto.take(True) == 'one'
    auto.finished(False)
    assert auto.paused and auto.take(True) is None
    auto.observe([job('one'), job('two'), job('three')], True)
    assert auto.take(True) is None
    auto.arm([job('one'), job('two'), job('three')])
    assert auto.take(True) is None
    auto.observe([job('four', created=4)], True)
    assert auto.take(True) == 'four'


def test_enabling_does_not_retroactively_send_jobs_received_while_disabled():
    auto = AutoSubmitQueue()
    auto.observe([job('old')], False)
    auto.arm([job('old')])
    auto.observe([job('old'), job('new')], True)
    assert auto.take(True) == 'new'


def test_preview_uses_browser_file_uri_not_a_shell_command(tmp_path):
    from tests.test_client import pdf_bytes
    from zgcaprint.desktop.integration import preview_pdf
    p = tmp_path/'test 中文 $(echo nope).PDF'
    p.write_bytes(pdf_bytes())
    calls = []
    preview_pdf(p, lambda uri: calls.append(uri) or True)
    assert calls == [p.resolve().as_uri()]


def test_browser_ipp_and_ppd_options_map_to_the_same_print_settings():
    from zgcaprint.cups.backend import printing_settings, options
    assert printing_settings(options('sides=two-sided-long-edge print-color-mode=monochrome')) == (2,1)
    assert printing_settings(options('Duplex=DuplexNoTumble ColorModel=Gray')) == (2,1)
    assert printing_settings(options('sides=two-sided-short-edge print-color-mode=color')) == (3,2)
    assert printing_settings(options('sides=one-sided print-color-mode=auto')) == (1,1)


def test_missing_preview_pdf_has_specific_error(tmp_path):
    import pytest
    from zgcaprint.desktop.integration import preview_pdf
    from zgcaprint.common.errors import PrintError
    with pytest.raises(PrintError,match='PDF 已不存在'):
        preview_pdf(tmp_path/'gone.pdf',lambda uri:True)
