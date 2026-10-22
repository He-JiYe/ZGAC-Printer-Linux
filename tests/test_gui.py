"""Opt-in tests run on a private Xvfb display, never the user's desktop."""
import os
import pytest

pytestmark = pytest.mark.skipif(os.environ.get('ZGCAPRINT_TEST_UI') != '1', reason='requires private virtual display')


@pytest.fixture
def app(tmp_path, monkeypatch):
    import tkinter as tk
    import zgcaprint.ui.window as gui
    monkeypatch.setattr(gui, 'queue_installed', lambda profile: False)
    root = tk.Tk()
    profile = {'base_url': 'https://ui-test.invalid/services', 'queue': 'TEST'}
    client = gui.PrintClientApp(tmp_path, root=root, profile=profile,
                spool_base=tmp_path/'spool', auto_start=False)
    root.update()
    yield client
    client.busy = False
    client.close()


@pytest.mark.parametrize('width,height', [(560,420), (640,480), (800,600), (1020,800)])
def test_submit_stays_visible_inside_window_when_resized(app, width, height):
    app.root.geometry(f'{width}x{height}')
    app.root.update()
    button = app.submit_button
    assert button.winfo_viewable()
    x = button.winfo_rootx()-app.root.winfo_rootx()
    y = button.winfo_rooty()-app.root.winfo_rooty()
    assert 0 <= x and 0 <= y
    assert x+button.winfo_width() <= app.root.winfo_width()
    assert y+button.winfo_height() <= app.root.winfo_height()
    assert app.footer.master is app.root


def test_small_window_scrolls_content_instead_of_hiding_actions(app):
    app.root.geometry('560x420')
    app.root.update()
    area = app.canvas.bbox('all')
    assert area[3] > app.canvas.winfo_height()
    app.canvas.yview_moveto(1)
    app.root.update()
    assert app.submit_button.winfo_viewable()


def test_long_status_cannot_push_submit_below_the_window(app):
    app.root.geometry('560x420')
    app.status.set('服务器提示：'+'这是一段很长的状态说明。'*40)
    app.root.update()
    b=app.submit_button
    bottom=b.winfo_rooty()-app.root.winfo_rooty()+b.winfo_height()
    assert bottom<=app.root.winfo_height()


def test_existing_spool_job_is_not_auto_submitted_on_start(tmp_path, monkeypatch):
    from tests.test_client import pdf_bytes
    from zgcaprint.printing.jobs import prepare
    from zgcaprint.ui.window import PrintClientApp
    import zgcaprint.ui.window as gui
    import tkinter as tk
    spool = tmp_path/'spool'
    old = prepare(spool/str(os.getuid()), pdf_bytes(), 'old.pdf', source='cups')
    monkeypatch.setattr(gui,'queue_installed',lambda profile:False)
    root=tk.Tk()
    app=PrintClientApp(tmp_path/'home',root=root,profile={'base_url':'https://ui.invalid/services','queue':'TEST'},
                       spool_base=spool,auto_start=False)
    assert old['id'] in app.automation.seen
    app.close()


def test_new_cups_job_is_submitted_once_without_second_confirmation(tmp_path, monkeypatch):
    import time
    import tkinter as tk
    import zgcaprint.ui.window as gui
    from tests.test_client import pdf_bytes
    from zgcaprint.printing.jobs import prepare, load_job, set_state
    calls=[]
    class Client:
        def __init__(self,*args):pass
        def submit(self,home,job_id,account,password):
            calls.append((job_id,account))
            j=load_job(home,job_id);set_state(home,j,'submitted',server_id=99)
            return j
    monkeypatch.setattr(gui,'queue_installed',lambda profile:True)
    def unexpected_confirmation(*args,**kwargs):
        raise AssertionError('browser print is already the user confirmation')
    monkeypatch.setattr(gui,'ConfirmDialog',unexpected_confirmation)
    home,spool=tmp_path/'home',tmp_path/'spool'
    root=tk.Tk()
    app=gui.PrintClientApp(home,root=root,profile={'base_url':'https://ui.invalid/services','queue':'TEST'},
        spool_base=spool,client_factory=Client,auto_start=False)
    app.user.set('student');app.cached.update(account='student',password='synthetic-test-password');app.logged_in=True
    j=prepare(spool/str(os.getuid()),pdf_bytes(),'browser.pdf',source='cups')
    app.watch()
    deadline=time.monotonic()+4
    while time.monotonic()<deadline and not calls:
        root.update();time.sleep(.01)
    assert calls==[(j['id'],'student')]
    deadline=time.monotonic()+.5
    while time.monotonic()<deadline:
        root.update();time.sleep(.01)
    assert len(calls)==1
    assert load_job(home,j['id'])['state']=='submitted'
    app.busy=False;app.close()


def test_close_to_tray_keeps_client_alive_and_show_restores_window(app):
    app.tray_ready=True
    app.hide();app.root.update()
    assert not app.closed and app.root.state()=='withdrawn'
    app.show();app.root.update()
    assert app.root.state()=='normal'



def pump(app,condition,seconds=4):
    import time
    end=time.monotonic()+seconds
    while time.monotonic()<end and not condition():
        app.root.update();time.sleep(.01)
    assert condition()


def log_in_locally(app):
    app.user.set('student');app.cached.update(account='student',password='synthetic-password')
    app.logged_in=True


def test_all_local_receipts_visible_regardless_of_old_web_annotation(app):
    from zgcaprint.printing.jobs import prepare, set_state
    from tests.test_client import pdf_bytes
    j=prepare(app.home,pdf_bytes(),'synthetic.pdf')
    set_state(app.home,j,'submitted',server_id=123,remote_state='not_pending')
    app.refresh()
    assert app.tree.exists(j['id'])
    assert app.tree.item(j['id'],'values')[-1]=='已提交'
    assert not hasattr(app,'web_client')


def test_settings_is_single_optional_window_and_main_menu_has_four_actions(app):
    assert app.settings_window is None
    assert [app.context_menu.entrycget(i,'label') for i in range(4)]==['打开','设置','注销','退出']
    app.context_menu.invoke(1);app.root.update()
    window=app.settings_window
    assert window.winfo_viewable()
    app.open_settings()
    assert app.settings_window is window
    app.close_settings()
    assert app.settings_window is None
    assert app.submit_button.winfo_viewable()


def test_manual_submit_has_one_confirmation_and_sends_only_after_accept(app,monkeypatch):
    from zgcaprint.printing.jobs import prepare, load_job, set_state
    from tests.test_client import pdf_bytes
    calls=[]
    class Client:
        def __init__(self,*args):pass
        def submit(self,home,job_id,account,password):
            calls.append(job_id)
            j=load_job(home,job_id);set_state(home,j,'submitted',server_id=456)
            return j
    app.client_factory=Client;log_in_locally(app)
    j=prepare(app.home,pdf_bytes(),'synthetic.pdf');app.refresh();app.tree.selection_set(j['id'])
    app.send();app.root.update()
    dialog=app.dialog
    assert dialog is not None and not calls
    app.send()
    assert app.dialog is dialog
    dialog.accept()
    pump(app,lambda:not app.busy)
    assert calls==[j['id']] and app.dialog is None
    assert '提交成功' in app.status.get()
    assert not [w for w in app.root.winfo_children() if w.winfo_class()=='Toplevel']


def test_submit_without_login_opens_settings_without_registering_job(app):
    from zgcaprint.printing.jobs import prepare, load_job
    from tests.test_client import pdf_bytes
    j=prepare(app.home,pdf_bytes(),'synthetic.pdf');app.refresh();app.tree.selection_set(j['id'])
    app.send();app.root.update()
    assert app.settings_window is not None and app.dialog is None
    assert load_job(app.home,j['id'])['state']=='prepared'


def test_failure_stays_inline_and_settings_can_close_during_operation(app):
    from zgcaprint.common.errors import PrintError
    app.open_settings();app.root.update()
    def fail():raise PrintError('合成错误：请核对作业。')
    app.start(fail,'处理中…',kind='settings')
    app.close_settings()
    pump(app,lambda:not app.busy)
    assert '合成错误' in app.status.get()
    assert not [w for w in app.root.winfo_children() if w.winfo_class()=='Toplevel']
    app.open_settings();app.root.update()
    assert app.settings_window.winfo_viewable()


def test_logout_preserves_cached_documents_and_remembered_credential(app):
    from zgcaprint.config.credentials import CredentialStore, remember_login, preferences
    from zgcaprint.printing.jobs import prepare, load_job
    from tests.test_client import pdf_bytes
    database={}
    def backend(op,server,account,password):
        if op=='store':database[account]=password;return True
        if op=='lookup':return database.get(account)
        if op=='clear':return database.pop(account,None)
    app.store=CredentialStore(app.profile['base_url'],backend)
    remember_login(app.home,app.store,'student','synthetic-password',True)
    j=prepare(app.home,pdf_bytes(),'synthetic.pdf')
    log_in_locally(app);app.auto_login.set(True)
    app.context_menu.invoke(2)
    assert not app.logged_in and app.cached['password'] is None
    assert app.store.get('student')=='synthetic-password'
    assert not preferences(app.home,app.profile['base_url'])['auto_login']
    assert load_job(app.home,j['id'])['state']=='prepared'


def test_confirmation_cancel_and_busy_exit_never_lose_a_job(app):
    from zgcaprint.printing.jobs import prepare, load_job
    from tests.test_client import pdf_bytes
    log_in_locally(app)
    j=prepare(app.home,pdf_bytes(),'长文档名称'*50+'.pdf');app.refresh();app.tree.selection_set(j['id'])
    app.send();app.root.update()
    w=app.dialog.window;b=app.dialog.accept_button
    assert b.winfo_rooty()+b.winfo_height()<=w.winfo_rooty()+w.winfo_height()
    app.dialog.close()
    assert app.dialog is None and load_job(app.home,j['id'])['state']=='prepared'
    app.set_busy(True);app.context_menu.invoke(3)
    assert not app.closed and '等待' in app.status.get()
    app.set_busy(False)


@pytest.mark.parametrize('message,remaining',[('已登录。',''),('已登录。 凭据未能保存。','凭据未能保存。')])
def test_login_status_only_appears_in_header_but_preserves_actionable_warning(app,message,remaining):
    app.user.set('student')
    app.events.put({'account':'student','password':'synthetic-only','message':message,'kind':'login'})
    app.poll();app.root.update()
    assert app.logged_in and app.badge.get()=='已登录'
    assert app.status.get()==remaining and app.settings_status.get()==remaining


def test_rounded_checkbox_keeps_keyboard_toggle_and_disabled_semantics(app):
    from tkinter import ttk
    app.open_settings();app.root.update()
    button=next(w for w in app.controls if isinstance(w,ttk.Checkbutton) and str(w.cget('variable'))==str(app.auto_submit))
    before=app.auto_submit.get()
    button.focus_force();app.root.update()
    button.event_generate('<KeyPress-space>');button.event_generate('<KeyRelease-space>');app.root.update()
    assert app.auto_submit.get()!=before
    button.state(['disabled']);value=app.auto_submit.get();button.invoke()
    assert app.auto_submit.get()==value


def test_retention_preference_survives_auto_submit_change(app):
    from zgcaprint.printing import cache
    app.retention.set(cache.POLICIES['forever']);app.change_retention()
    app.auto_submit.set(False);app.toggle_submission()
    assert cache.read_policy(app.home,app.profile['base_url'])=='forever'


def test_saved_credentials_can_be_removed_after_logout_without_logging_in(app):
    from zgcaprint.config.credentials import CredentialStore, remember_login, preferences
    database={}
    def backend(op,server,account,password):
        if op=='store':database[account]=password;return True
        if op=='lookup':return database.get(account)
        if op=='clear':return database.pop(account,None)
    app.store=CredentialStore(app.profile['base_url'],backend)
    remember_login(app.home,app.store,'student','synthetic-only',True)
    app.user.set('student');app.remember.set(True)
    app.logout();app.remember.set(False);app.toggle_remember()
    pump(app,lambda:not app.busy)
    assert app.store.get('student') is None and not app.logged_in
    assert not preferences(app.home,app.profile['base_url'])['remember']


def test_submitted_receipt_without_pdf_disables_preview_with_clear_explanation(app,monkeypatch):
    from zgcaprint.printing.jobs import prepare, set_state
    from tests.test_client import pdf_bytes
    j=prepare(app.home,pdf_bytes(),'synthetic.pdf');set_state(app.home,j,'submitted',server_id=123)
    (app.home/'jobs'/j['id']/'document.pdf').unlink()
    app.refresh();app.tree.selection_set(j['id']);app.root.update()
    assert app.preview_button.instate(['disabled'])
    assert '仅回执' in app.summary.get()
    def wrong_preview(*args):raise AssertionError('missing PDF must not launch a browser')
    monkeypatch.setattr('zgcaprint.ui.window.preview_pdf',wrong_preview)
    app.preview()
    assert 'PDF 已清理' in app.status.get()


def test_pending_document_preview_uses_its_local_pdf(app,monkeypatch):
    from zgcaprint.printing.jobs import prepare
    from tests.test_client import pdf_bytes
    calls=[]
    j=prepare(app.home,pdf_bytes(),'synthetic.pdf');app.refresh();app.tree.selection_set(j['id']);app.root.update()
    monkeypatch.setattr('zgcaprint.ui.window.preview_pdf',lambda path:calls.append(path))
    assert not app.preview_button.instate(['disabled'])
    app.preview();pump(app,lambda:not app.busy)
    assert calls==[app.home/'jobs'/j['id']/'document.pdf']
    assert '已在浏览器打开' in app.status.get()


@pytest.mark.parametrize('width,height',[(360,260),(500,340),(1200,880)])
def test_clear_dialog_keeps_full_text_and_actions_reachable_when_resized(app,width,height):
    from zgcaprint.ui.dialogs import ConfirmDialog
    document='课程阅读材料'*30+'.pdf'
    paragraph='仅清除本机记录，不取消服务器任务。'*12
    dialog=ConfirmDialog(app.root,'清除本地记录',document,[('影响范围',paragraph)],'清除',lambda:None,lambda d:None)
    try:
        dialog.window.geometry(f'{width}x{height}');app.root.update()
        assert dialog.document_label.cget('text')==document
        assert dialog.fields[0][1].cget('text')==paragraph
        for button in [dialog.accept_button,dialog.cancel_button]:
            x=button.winfo_rootx()-dialog.window.winfo_rootx();y=button.winfo_rooty()-dialog.window.winfo_rooty()
            assert 0<=x and x+button.winfo_width()<=dialog.window.winfo_width()
            assert 0<=y and y+button.winfo_height()<=dialog.window.winfo_height()
        dialog.canvas.yview_moveto(1);app.root.update()
        last=dialog.fields[-1][1]
        assert last.winfo_rooty()+last.winfo_height()<=dialog.canvas.winfo_rooty()+dialog.canvas.winfo_height()
    finally:dialog.close()


def test_settings_action_stays_visible_in_small_and_large_windows(app):
    app.open_settings()
    for width,height in [(420,420),(1100,880)]:
        app.settings_window.geometry(f'{width}x{height}');app.root.update()
        w=app.settings_window;b=app.settings_done
        assert b.winfo_rootx()+b.winfo_width()<=w.winfo_rootx()+w.winfo_width()
        assert b.winfo_rooty()+b.winfo_height()<=w.winfo_rooty()+w.winfo_height()


def test_new_source_file_can_be_previewed_when_an_old_receipt_was_selected(app,monkeypatch):
    from zgcaprint.printing.jobs import prepare, set_state
    from tests.test_client import pdf_bytes
    j=prepare(app.home,pdf_bytes(),'receipt.pdf');set_state(app.home,j,'submitted',server_id=123)
    (app.home/'jobs'/j['id']/'document.pdf').unlink()
    app.refresh();app.tree.selection_set(j['id']);app.root.update()
    source=app.home/'source.pdf';source.write_bytes(pdf_bytes())
    app.file_var.set(str(source));app.root.update()
    assert not app.tree.selection() and not app.preview_button.instate(['disabled'])
    calls=[];monkeypatch.setattr('zgcaprint.ui.window.preview_pdf',lambda path:calls.append(path))
    app.preview();pump(app,lambda:not app.busy)
    assert calls==[str(source)]
