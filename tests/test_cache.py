"""Receipt retention never deletes pending documents or permits CUPS replay."""
from pathlib import Path
import os
import pytest

from zgcaprint.printing import cache
from zgcaprint.printing.completed import completed_ids
from zgcaprint.common.errors import PrintError
from zgcaprint.printing.jobs import prepare, set_state, load_job, adopt_cups_jobs, remove_job
from zgcaprint.config.profile import json_write
from tests.test_client import pdf_bytes

NOW=200000


def submitted(home,age):
    job=prepare(home,pdf_bytes(),'synthetic.pdf')
    set_state(home,job,'submitted',server_id=123,submitted_at=NOW-age)
    return job


def test_one_day_only_removes_expired_submitted_receipts(tmp_path):
    old=submitted(tmp_path,86401);recent=submitted(tmp_path,86399)
    assert cache.prune(tmp_path,'day',now=NOW)==1
    assert not (tmp_path/'jobs'/old['id']).exists()
    assert load_job(tmp_path,recent['id'])['state']=='submitted'
    assert old['id'] in completed_ids(tmp_path)


@pytest.mark.parametrize('state',['prepared','registering','registered','uploading','uploaded','committing','uncertain'])
def test_pending_or_unconfirmed_documents_survive_all_retention_modes(tmp_path,state):
    job=prepare(tmp_path,pdf_bytes(),'keep.pdf')
    set_state(tmp_path,job,state,server_id=123,created_at=1)
    job['updated_at']=1;json_write(tmp_path/'jobs'/job['id']/'job.json',job)
    assert cache.prune(tmp_path,'day',now=NOW)==0
    assert cache.prune(tmp_path,'startup',on_start=True,now=NOW)==0
    assert (tmp_path/'jobs'/job['id']/'document.pdf').exists()
    assert load_job(tmp_path,job['id'])['state']==state


def test_startup_policy_only_cleans_at_start_and_forever_keeps_receipts(tmp_path):
    job=submitted(tmp_path,1)
    assert cache.prune(tmp_path,'startup',now=NOW)==0
    assert cache.prune(tmp_path,'forever',on_start=True,now=NOW)==0
    assert load_job(tmp_path,job['id'])['state']=='submitted'
    assert cache.prune(tmp_path,'startup',on_start=True,now=NOW)==1


def test_failed_duplicate_guard_write_preserves_receipt(tmp_path,monkeypatch):
    job=submitted(tmp_path,90000)
    def fail(*args):raise PrintError('synthetic write failure')
    monkeypatch.setattr(cache,'remember_completed',fail)
    with pytest.raises(PrintError):cache.prune(tmp_path,'day',now=NOW)
    assert load_job(tmp_path,job['id'])['state']=='submitted'


def test_corrupt_duplicate_index_preserves_receipt(tmp_path):
    job=submitted(tmp_path,90000)
    json_write(tmp_path/'completed-index.json',{'schema':1,'ids':['invalid']})
    with pytest.raises(PrintError):cache.prune(tmp_path,'day',now=NOW)
    assert (tmp_path/'jobs'/job['id']).exists()


def test_cups_retry_after_receipt_cleanup_cannot_be_reimported(tmp_path):
    home,spool=tmp_path/'home',tmp_path/'spool'
    source=spool/str(os.getuid());raw=pdf_bytes()
    job=prepare(source,raw,'synthetic.pdf',dedup_token='test-queue:123',source='cups')
    adopt_cups_jobs(home,spool)
    local=load_job(home,job['id'])
    set_state(home,local,'submitted',server_id=123,submitted_at=1)
    assert cache.prune(home,'day',now=NOW)==1
    retry=prepare(source,raw,'synthetic.pdf',dedup_token='test-queue:123',source='cups')
    assert retry['id']==job['id']
    assert adopt_cups_jobs(home,spool)==[]
    assert not (home/'jobs'/job['id']).exists()
    assert not (source/'jobs'/job['id']).exists()
    index=(home/'completed-index.json').read_text()
    assert 'synthetic.pdf' not in index and 'server_id' not in index and 'account' not in index


def test_manual_receipt_removal_also_keeps_duplicate_guard(tmp_path):
    job=submitted(tmp_path,1)
    remove_job(tmp_path,job['id'])
    assert job['id'] in completed_ids(tmp_path)


def test_legacy_receipts_use_updated_time_and_missing_time_is_preserved(tmp_path):
    job=submitted(tmp_path,1);job.pop('submitted_at');job['updated_at']=1
    json_write(tmp_path/'jobs'/job['id']/'job.json',job)
    assert cache.prune(tmp_path,'day',now=NOW)==1
    second=submitted(tmp_path,1)
    for key in ['submitted_at','created_at','updated_at']:second.pop(key,None)
    json_write(tmp_path/'jobs'/second['id']/'job.json',second)
    assert cache.prune(tmp_path,'day',now=NOW)==0


def test_policy_is_scoped_to_server_and_defaults_to_one_day(tmp_path):
    assert cache.read_policy(tmp_path,'https://one.invalid')=='day'
    json_write(tmp_path/'ui-settings.json',{'server':'https://one.invalid','completed_retention':'startup'})
    assert cache.read_policy(tmp_path,'https://one.invalid')=='startup'
    assert cache.read_policy(tmp_path,'https://two.invalid')=='day'


def test_cleanup_during_cups_import_still_suppresses_the_retry(tmp_path,monkeypatch):
    import zgcaprint.printing.jobs as jobs
    home,spool=tmp_path/'home',tmp_path/'spool'
    source=spool/str(os.getuid());raw=pdf_bytes()
    job=prepare(source,raw,'synthetic.pdf',dedup_token='queue:123',source='cups')
    adopt_cups_jobs(home,spool)
    local=load_job(home,job['id']);set_state(home,local,'submitted',server_id=123,submitted_at=1)
    prepare(source,raw,'synthetic.pdf',dedup_token='queue:123',source='cups')
    original=jobs.verified_pdf
    def interleaved(source_home,metadata):
        data=original(source_home,metadata)
        assert cache.prune(home,'day',now=NOW)==1
        return data
    monkeypatch.setattr(jobs,'verified_pdf',interleaved)
    assert adopt_cups_jobs(home,spool)==[]
    assert not (home/'jobs'/job['id']).exists()
