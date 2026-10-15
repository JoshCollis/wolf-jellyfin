import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('session',ROOT/'overlay/opt/wolf-jellyfin/session.py')
        cls.s=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.s)
    def test_decimal_parent_mode(self):
        self.assertEqual(self.s.parent_mode('width: 1920 px, height: 1080 px, refresh: 59.940 Hz,\n flags: current preferred'),(1920,1080,59940))
    def test_parent_ambiguous_refused(self):
        with self.assertRaises(ValueError): self.s.parent_mode('')
    def test_mode_contract(self):
        env={'GAMESCOPE_WIDTH':'1920','GAMESCOPE_HEIGHT':'1080','GAMESCOPE_REFRESH':'60'}
        self.assertEqual(self.s.requested(env),(1920,1080,60000))
        with self.assertRaises(ValueError): self.s.agree(self.s.requested(env),(1920,1080,59940))
        for bad in ['0','-1','garbage','999999']:
            with self.assertRaises(ValueError): self.s.requested(env|{'GAMESCOPE_REFRESH':bad})
    def test_profile_name_not_a_path(self):
        for name in ['../other','/root','', 'bad name']:
            with self.assertRaises(ValueError): self.s.profile_name(name)
        self.assertEqual(self.s.profile_name('family-1'),'family-1')
    def test_home_lease_excludes_second_writer(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.s.lease(Path(d))
            with self.assertRaises(BlockingIOError): self.s.lease(Path(d))
            a.close();self.s.lease(Path(d)).close()
    def test_lock_symlink_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'.wolf-jellyfin.lock').symlink_to(p/'victim')
            with self.assertRaises(OSError): self.s.lease(p)
    def test_lock_fifo_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);os.mkfifo(p/'.wolf-jellyfin.lock')
            with self.assertRaisesRegex(ValueError,'regular file'): self.s.lease(p)
    def test_multiple_current_outputs_refused(self):
        mode='width: 1280 px, height: 720 px, refresh: 60000 mHz,\n flags: current preferred\n'
        with self.assertRaises(ValueError): self.s.parent_mode(mode*2)
    def test_startup_stop_before_pid_handoff(self):
        import signal
        with tempfile.TemporaryDirectory() as d:
            env={'HOME':d,'XDG_RUNTIME_DIR':d,'GAMESCOPE_WIDTH':'1280',
                 'GAMESCOPE_HEIGHT':'720','GAMESCOPE_REFRESH':'60'}
            handlers={}
            child=Mock(pid=12345)
            def launch(*args,**kwargs):
                self.assertEqual(kwargs['env'].get('WOLF_JELLYFIN_KIOSK'),'1')
                handlers[signal.SIGTERM](signal.SIGTERM,None)
                return child
            with patch.dict(os.environ,env,clear=True), \
                 patch.object(self.s.os,'getuid',return_value=1000), \
                 patch.object(self.s,'read_parent',return_value=(1280,720,60000)), \
                 patch.object(self.s.subprocess,'run',return_value=Mock(stdout='')) as run, \
                 patch.object(self.s.signal,'signal',side_effect=lambda sig,fn:handlers.update({sig:fn})), \
                 patch.object(self.s.subprocess,'Popen',side_effect=launch), \
                 patch.object(self.s,'shutdown') as shutdown:
                self.assertEqual(self.s.main(),0)
                shutdown.assert_called_once_with(child,None)
                self.assertEqual(len(run.call_args_list),2)
                for call in run.call_args_list:
                    self.assertEqual(call.kwargs['timeout'],15)
    def test_client_fullscreen_no_unsafe_flags(self):
        args=self.s.client_args('Default',[])
        self.assertIn('--fullscreen',args);self.assertIn('--tv',args)
        self.assertNotIn('--no-sandbox',args)
        self.assertEqual(args[-2:],['--profile','Default'])
    def test_graceful_shutdown_does_not_kill_renderer_first(self):
        import subprocess,sys,time
        with tempfile.TemporaryDirectory() as d:
            marker=Path(d)/'marker';ready=Path(d)/'ready'
            code="import subprocess,signal,time,sys,pathlib; c=subprocess.Popen(['sleep','30']); marker=pathlib.Path(sys.argv[1]); ready=pathlib.Path(sys.argv[2]);\ndef stop(*a):\n time.sleep(.2); marker.write_text('survived' if c.poll() is None else 'killed-first'); sys.exit(0)\nsignal.signal(signal.SIGTERM,stop); ready.touch(); time.sleep(30)"
            p=subprocess.Popen([sys.executable,'-c',code,str(marker),str(ready)],start_new_session=True)
            try:
                for _ in range(50):
                    if ready.exists():break
                    time.sleep(.02)
                self.assertTrue(ready.exists())
                self.s.shutdown(p,p.pid)
                self.assertEqual(marker.read_text(),'survived')
            finally:
                try:os.killpg(p.pid,9)
                except ProcessLookupError:pass
                p.wait()
    def test_exit_cannot_hide_parent_mode_loss(self):
        mode=(1920,1080,60000)
        self.assertEqual(self.s.completed(0,mode,mode),0)
        self.assertEqual(self.s.completed(-15,mode,mode),143)
        self.assertEqual(self.s.completed(0,mode,(1920,1080,120000)),75)
    def test_changed_parent_requires_recreation(self):
        self.assertFalse(self.s.changed((1920,1080,60000),(1920,1080,60000)))
        self.assertTrue(self.s.changed((1920,1080,60000),(1920,1080,120000)))
if __name__=='__main__':unittest.main()
