"""Release asset compatibility and safe activation: offline fixture tests."""
import io
import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_editor.release_feed import (APP_VERSION, APP_ID, ASSET_NAME, LOCAL_EXE_NAME,
    RELEASES, release_download_urls, parse_release, parse_update_info, validated_download)
from drawing_editor import onefile_update as update
from build.release_metadata import build_metadata
from build.approve_update import approved_metadata

VER='.'.join(str(v) for v in (*map(int, APP_VERSION.split('.')[:2]), int(APP_VERSION.split('.')[-1])+1))
SHA='6be1ef16d85b388bf5f734bef19c6ab28ac574dc8e11594e8f21f5dd171a41e1'
SIZE=74442984

def feed(version=VER):
    return dict(schema_version=1, app_id=APP_ID, platform='windows-x64', package_kind='onefile_exe',
                latest_version=version, update_endpoint_configured=True, official_release=True,
                automatic_update_available=True, authenticode_required=True,
                release_url=RELEASES+'/tag/v'+version, download_url=release_download_urls(version)[0],
                download_file_name=ASSET_NAME, sha256=SHA, file_size_bytes=SIZE)

def asset(d):
    return dict(tag_name='v'+d['latest_version'],draft=False,prerelease=False,assets=[dict(name=ASSET_NAME,
                state='uploaded',size=d['file_size_bytes'],digest='sha256:'+d['sha256'],browser_download_url=d['download_url'])])

class ContractTests(unittest.TestCase):
    def test_actual_110_metadata(self):
        d=feed('1.1.0'); r=parse_release(json.dumps(d), current='1.0.0')
        self.assertEqual((r.download,r.sha256,r.size),(d['download_url'],SHA,SIZE)); self.assertTrue(r.automatic)
        self.assertIsNone(parse_release(json.dumps(d),current='1.1.0'))
    def test_legacy_asset(self):
        d=feed();d.update(download_url=release_download_urls(VER)[1], download_file_name=LOCAL_EXE_NAME)
        self.assertEqual(parse_release(json.dumps(d)).download,d['download_url'])
    def test_bad_urls(self):
        for url in ('https://example.com/x.exe',RELEASES+'/download/v9.9.9/'+ASSET_NAME,release_download_urls(VER)[0]+'?x=1',release_download_urls(VER)[0]+'#x',RELEASES+'/download/v'+VER+'/other.exe'):
            d=feed();d['download_url']=url
            with self.subTest(url=url),self.assertRaises(ValueError):parse_release(json.dumps(d))
    def test_name_mismatch(self):
        d=feed(); d['download_file_name']=LOCAL_EXE_NAME
        with self.assertRaises(ValueError):parse_release(json.dumps(d))
    def test_disabled_and_same_version(self):
        d=feed();d['update_endpoint_configured']=False;self.assertIsNone(parse_update_info(json.dumps(d)).release)
        self.assertIsNone(parse_release(json.dumps(feed(APP_VERSION))))
    def test_target_both_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in (LOCAL_EXE_NAME,ASSET_NAME,'other.exe'):
                p=Path(tmp)/name;p.touch()
                if name=='other.exe':
                    with self.assertRaises(update.UpdateError):update._target(p)
                else:self.assertEqual(update._target(p),p.resolve())
    def test_redirect_policy(self):
        u=release_download_urls(VER)[0];update.check_update_url(u,u);update.check_update_url('https://release-assets.githubusercontent.com/a?token=x',u)
        for bad in ('http://release-assets.githubusercontent.com/a','https://example.com/a','https://release-assets.githubusercontent.com@evil.test/a'):
            with self.assertRaises(update.UpdateError):update.check_update_url(bad,u)
    def test_hash_size_and_cancel(self):
        data=b'test payload'; h=hashlib.sha256(data).hexdigest();out=io.BytesIO()
        update.stream_verified(io.BytesIO(data),out,len(data),h);self.assertEqual(out.getvalue(),data)
        for size,sha,cancel in ((len(data)+1,h,False),(len(data),'a'*64,False),(len(data),h,True)):
            with self.assertRaises(update.UpdateError):update.stream_verified(io.BytesIO(data),io.BytesIO(),size,sha,cancelled=lambda:cancel)
    def test_stage_actual_asset_and_local_name_mock(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/ASSET_NAME;p.write_bytes(b'old');payload=b'new test bytes';d=feed();d.update(sha256=hashlib.sha256(payload).hexdigest(),file_size_bytes=len(payload));r=parse_release(json.dumps(d))
            class Response(io.BytesIO):
                def geturl(self):return r.download
            from drawing_editor.control import Policy
            from types import SimpleNamespace
            with patch.object(update.sys,'platform','win32'),patch.object(update.sys,'frozen',True,create=True),patch.object(update.sys,'executable',str(p)),patch.object(update,'check_policy',return_value=Policy()),patch.object(update,'build_opener') as op,patch.object(update.subprocess,'run',side_effect=[SimpleNamespace(returncode=42), SimpleNamespace(returncode=0)]):
                op.return_value.open.return_value=Response(payload);prep=update.stage_update(r);self.assertEqual(Path(prep[0]).read_bytes(),payload); self.assertEqual(prep[1],str(p.resolve()));update.discard_prepared(prep)
            self.assertEqual(p.read_bytes(),b'old')
    def test_helper_replaces_both_targets_and_rolls_back_on_launch_failure(self):
        from drawing_editor.control import Policy
        for name in (LOCAL_EXE_NAME, ASSET_NAME):
            for launch_failure in (False, True):
                with self.subTest(name=name, failure=launch_failure), tempfile.TemporaryDirectory() as tmp:
                    target=Path(tmp)/name; target.write_bytes(b'old')
                    stage=Path(tmp)/'.sunrise-update-abcdefgh';stage.mkdir();candidate=stage/'candidate.exe';candidate.write_bytes(b'new')
                    args=[str(target),update.digest(target),update.digest(candidate),APP_VERSION,'0.9.0','123']
                    def launch(*args, **kwargs):
                        if launch_failure: raise OSError('launch failed')
                        (stage / update.STARTUP_PENDING).unlink()
                    with patch.object(update.sys,'platform','win32'),patch.object(update.sys,'frozen',True,create=True),patch.object(update.sys,'executable',str(candidate)),patch.object(update,'verify_release_authority'),patch.object(update,'_wait_for_exit'),patch.object(update,'check_policy',return_value=Policy()),patch.object(update.subprocess,'Popen',side_effect=launch):
                        if launch_failure:
                            with self.assertRaises(OSError):update.apply_update(args)
                            self.assertEqual(target.read_bytes(),b'old')
                        else:
                            self.assertEqual(update.apply_update(args),0)
                            self.assertEqual(target.read_bytes(),b'new');self.assertEqual((stage/'rollback.exe').read_bytes(),b'old')

    def test_startup_early_exit_rolls_back_timeout_preserves(self):
        from drawing_editor.control import Policy
        from types import SimpleNamespace
        for exited in (True, False):
            with self.subTest(exited=exited), tempfile.TemporaryDirectory() as tmp:
                target=Path(tmp)/ASSET_NAME;target.write_bytes(b'old')
                stage=Path(tmp)/'.sunrise-update-abcdefgh';stage.mkdir()
                candidate=stage/'candidate.exe';candidate.write_bytes(b'new')
                args=[str(target),update.digest(target),update.digest(candidate),APP_VERSION,'0.9.0','123']
                proc=SimpleNamespace(poll=lambda: 1 if exited else None)
                with patch.object(update.sys,'platform','win32'),patch.object(update.sys,'frozen',True,create=True),patch.object(update.sys,'executable',str(candidate)),patch.object(update,'verify_release_authority'),patch.object(update,'_wait_for_exit'),patch.object(update,'check_policy',return_value=Policy()),patch.object(update.subprocess,'Popen',return_value=proc),patch.object(update.time,'monotonic',side_effect=[0, 0, 121]):
                    with self.assertRaises(update.UpdateError):update.apply_update(args)
                self.assertEqual(target.read_bytes(), b'old' if exited else b'new')
                if not exited:self.assertEqual((stage/'rollback.exe').read_bytes(),b'old')
                self.assertTrue((stage/update.STARTUP_PENDING).exists())

    def test_official_feed_mismatch_blocks_before_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/ASSET_NAME;target.write_bytes(b'old');stage=Path(tmp)/'.sunrise-update-abcdefgh';stage.mkdir();candidate=stage/'candidate.exe';candidate.write_bytes(b'new')
            args=[str(target),update.digest(target),update.digest(candidate),APP_VERSION,'0.9.0','123']
            with patch.object(update.sys,'platform','win32'),patch.object(update.sys,'frozen',True,create=True),patch.object(update.sys,'executable',str(candidate)),patch.object(update,'verify_release_authority',side_effect=update.UpdateError('feed mismatch')),patch.object(update,'_wait_for_exit') as wait:
                with self.assertRaises(update.UpdateError):update.apply_update(args)
                wait.assert_not_called();self.assertEqual(target.read_bytes(),b'old')

    def test_helper_authority_uses_official_feed(self):
        d = feed(VER)
        with patch.object(update, 'fetch_text', return_value=json.dumps(d)) as fetch:
            update.verify_release_authority(APP_VERSION, VER, SHA, SIZE)
            fetch.assert_called_once_with('latest.json')
            for sha, size in (('a'*64, SIZE), (SHA, SIZE+1)):
                with self.assertRaises(update.UpdateError):
                    update.verify_release_authority(APP_VERSION, VER, sha, size)
        d['automatic_update_available'] = False
        with patch.object(update, 'fetch_text', return_value=json.dumps(d)):
            with self.assertRaises(update.UpdateError):
                update.verify_release_authority(APP_VERSION, VER, SHA, SIZE)

    def test_build_metadata_canonical_but_inactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/LOCAL_EXE_NAME;p.write_bytes(b'test');sha=update.digest(p);d=json.loads(build_metadata(p,sha,{'sha256':sha,'trust':'TRUSTED_BY_WINDOWS_POLICY'})['latest.json'])
            self.assertEqual(d['download_file_name'],ASSET_NAME);self.assertEqual(d['download_url'],release_download_urls(APP_VERSION)[0]);self.assertFalse(d['automatic_update_available'])
    def test_approval_exact_asset(self):
        d=feed('1.1.0');d.update(update_endpoint_configured=False,official_release=False,automatic_update_available=False); a=asset(d); x=approved_metadata(d,a,version='1.1.0',old_version='1.0.0',sha=SHA,size=SIZE,signature_trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY')
        self.assertTrue(x['automatic_update_available']);self.assertFalse(d['automatic_update_available']);self.assertEqual(x['signature_trust'],'SELF_SIGNED_UNTRUSTED_TEST_ONLY')
    def test_approval_rejects_unverified_signature_status(self):
        d=feed('1.1.0')
        with self.assertRaises(ValueError):approved_metadata(d,asset(d),version='1.1.0',old_version='1.0.0',sha=SHA,size=SIZE,signature_trust='UNKNOWN')
    def test_approval_rejects_mismatch(self):
        d=feed('1.1.0')
        for field,value in [('digest','sha256:'+'a'*64),('size',SIZE+1),('state','new'),('browser_download_url','https://example.com/a')]:
            a=asset(d);a['assets'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):approved_metadata(d,a,version='1.1.0',old_version='1.0.0',sha=SHA,size=SIZE,signature_trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY')
        a=asset(d);a['draft']=True
        with self.assertRaises(ValueError): approved_metadata(d,a,version='1.1.0',old_version='1.0.0',sha=SHA,size=SIZE,signature_trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY')
if __name__=='__main__': unittest.main(verbosity=2)
