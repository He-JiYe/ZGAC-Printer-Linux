"""Persist only the selected directory, retaining existing printing preferences."""
from pathlib import Path
from zgcaprint.config.profile import json_write,read_private
from zgcaprint.ui.file_picker import initial_directory,remember_directory


def test_last_directory_survives_restart_and_stores_no_document_name(tmp_path):
    folder=tmp_path/'documents';folder.mkdir()
    home=tmp_path/'client'
    remember_directory(home,folder/'personal-name.pdf')
    assert initial_directory(home)==folder
    data=(home/'file-dialog.json').read_text()
    assert 'personal-name.pdf' not in data and (home/'file-dialog.json').stat().st_mode & 0o077==0
    json_write(home/'ui-settings.json',{'auto_submit_cups':True})
    assert initial_directory(home)==folder
    assert read_private(home/'ui-settings.json')['auto_submit_cups'] is True


def test_removed_or_invalid_directory_falls_back_to_home(tmp_path,monkeypatch):
    user=tmp_path/'user';user.mkdir()
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:user))
    home=tmp_path/'client'
    json_write(home/'file-dialog.json',{'last_directory':str(tmp_path/'missing')})
    assert initial_directory(home)==user
    json_write(home/'file-dialog.json',{'last_directory':['invalid']})
    assert initial_directory(home)==user
