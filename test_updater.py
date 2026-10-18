import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

import pytest

import build_updater


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_bundle(root, exe=b"old executable"):
    (root / "_internal").mkdir(parents=True)
    (root / "frames").mkdir()
    (root / "BunnymanDesktopPet.exe").write_bytes(exe)
    (root / "_internal/python313.dll").write_bytes(b"runtime sentinel")
    (root / "_internal/Qt6Core.dll").write_bytes(b"Qt runtime sentinel")
    (root / "frames/idle.png").write_bytes(b"frame sentinel")
    (root / "manifest.json").write_text(json.dumps({
        "animations": {"idle": {"frames": {"cozy": ["frames/idle.png"]}}},
    }), encoding="utf-8")
    (root / "README.md").write_bytes(b"old guide")
    (root / "personal.txt").write_bytes(b"keep me")
    return root


def test_builder_only_embeds_changes_and_relative_paths(tmp_path):
    old = write_bundle(tmp_path / "old")
    new = write_bundle(tmp_path / "new", b"new executable")
    (new / "README.md").write_bytes(b"new guide")
    config = build_updater.prepare_payload(old, new, tmp_path / "work", "0.1.1")
    assert {item["path"] for item in config["files"]} == {"BunnymanDesktopPet.exe", "README.md"}
    assert config["test_mode"] is False
    assert config["required_runtime_files"] == ["_internal/Qt6Core.dll", "_internal/python313.dll"]
    assert config["allowed_base_exe_sha256"] == [digest(b"old executable"), digest(b"new executable")]
    assert str(tmp_path) not in json.dumps(config)
    with zipfile.ZipFile(tmp_path / "work/payload.zip") as archive:
        assert archive.testzip() is None
        assert archive.read("README.md") == b"new guide"


def test_builder_refuses_an_incomplete_base(tmp_path):
    old = write_bundle(tmp_path / "old")
    (old / "_internal/python313.dll").unlink()
    with pytest.raises(ValueError, match="python313"):
        build_updater.prepare_payload(old, tmp_path / "new", tmp_path / "work", "0.1.1")


def test_one_updater_covers_all_supported_baselines(tmp_path):
    old = write_bundle(tmp_path / "old", b"v0")
    middle = write_bundle(tmp_path / "middle", b"v1")
    new = write_bundle(tmp_path / "new", b"v2")
    # A file unchanged from the oldest base must still be restored for v1.
    (middle / "README.md").write_bytes(b"intermediate guide")
    config = build_updater.prepare_payload(old, new, tmp_path / "work", "0.1.2", [middle])
    assert set(config["allowed_base_exe_sha256"]) == {digest(b"v0"), digest(b"v1"), digest(b"v2")}
    assert {item["path"] for item in config["files"]} == {"BunnymanDesktopPet.exe", "README.md"}
    assert "/v0.1.2/" in config["full_download_url"]
    with zipfile.ZipFile(tmp_path / "work/payload.zip") as archive:
        for base in (old, middle):
            for relative, source in build_updater.bundle_files(new).items():
                actual = archive.read(relative) if relative in archive.namelist() else (base / relative).read_bytes()
                assert actual == source.read_bytes()


def test_extra_baselines_must_be_complete_and_versions_plain(tmp_path):
    old = write_bundle(tmp_path / "old")
    new = write_bundle(tmp_path / "new", b"new")
    extra = write_bundle(tmp_path / "extra")
    (extra / "_internal/python313.dll").unlink()
    with pytest.raises(ValueError, match="python313"):
        build_updater.prepare_payload(old, new, tmp_path / "work", "0.1.2", [extra])
    with pytest.raises(ValueError, match="Version"):
        build_updater.prepare_payload(old, new, tmp_path / "work", "../latest")


@pytest.fixture(scope="module")
def native_helpers(tmp_path_factory):
    if os.name != "nt":
        pytest.skip("Windows updater executable integration")
    try:
        compiler = build_updater.compiler_path()
    except ValueError:
        pytest.skip("Windows .NET Framework compiler is unavailable")
    work = tmp_path_factory.mktemp("u")
    old_source = work / "old.cs"
    old_source.write_text('''
using System; using System.Windows.Forms;
class OldPet { [STAThread] static void Main() {
 var form=new Form(); form.Text="Updater regression fixture";
 form.ShowInTaskbar=false; form.Opacity=0;
 form.FormClosing+=(s,e)=>{e.Cancel=true;form.Hide();};
 Application.Run(form);
} }
''', encoding="utf-8")
    new_source = work / "new.cs"
    new_source.write_text('''
using System; using System.IO;
class NewPet { static void Main() {
 File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"launched.txt"),"new version");
} }
''', encoding="utf-8")
    for name in ("old", "new"):
        subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64",
                        "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                        f"/out:{work / (name + '.exe')}", str(work / (name + '.cs'))],
                       check=True, capture_output=True, timeout=30)
    old_bytes = (work / "old.exe").read_bytes()
    new_bytes = (work / "new.exe").read_bytes()
    files = {"BunnymanDesktopPet.exe": new_bytes, "README.md": b"new guide",
             "_internal/new-file.txt": b"new runtime companion"}

    def helper(name, payload=None, paths=None, test_mode=True):
        folder = work / name
        folder.mkdir()
        data = payload or files
        config = {"version": "0.1.1", "app_exe": "BunnymanDesktopPet.exe",
                  "full_download_url": "https://github.com/hydrangeia/bunnyman-desktop-pet/releases/tag/v0.1.1",
                  "allowed_base_exe_sha256": [digest(old_bytes), digest(new_bytes)], "test_mode": test_mode,
                  "required_runtime_files": ["_internal/python313.dll", "_internal/Qt6Core.dll"],
                  "files": [{"path": path, "sha256": digest(content)} for path, content in (paths or data).items()]}
        with zipfile.ZipFile(folder / "payload.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path, content in data.items():
                archive.writestr(path, content)
        (folder / "manifest.json").write_text(json.dumps(config), encoding="utf-8")
        output = folder / "update.exe"
        build_updater.compile_updater(folder, output, compiler)
        return output

    return {"exe": helper("good"), "production": helper("production", test_mode=False),
            "old": old_bytes, "new": new_bytes, "files": files,
            "traversal": helper("unsafe", {"../outside.txt": b"bad"}),
            "bad_hash": helper("bad-hash", {"README.md": b"tampered"}, {"README.md": b"expected"})}


def run_update(exe, target, report, *flags):
    result = subprocess.run([str(exe), "--target", str(target), "--silent", "--report", str(report), *flags],
                            capture_output=True, text=True, timeout=30)
    assert report.is_file(), result.stdout + result.stderr
    return result.returncode, json.loads(report.read_text(encoding="utf-8-sig"))


def test_native_update_backs_up_replaces_and_preserves_resources(native_helpers, tmp_path):
    root = write_bundle(tmp_path / "pet", native_helpers["old"])
    code, report = run_update(native_helpers["exe"], root, tmp_path / "r.json", "--no-launch")
    assert code == 0 and report["ok"], report
    for path, contents in native_helpers["files"].items():
        assert (root / path).read_bytes() == contents
    assert (root / "personal.txt").read_bytes() == b"keep me"
    assert (root / "_internal/python313.dll").read_bytes() == b"runtime sentinel"
    backup = Path(report["backup_path"])
    assert (backup / "BunnymanDesktopPet.exe").read_bytes() == native_helpers["old"]
    assert (backup / "README.md").read_bytes() == b"old guide"


def test_native_update_rolls_back_replaced_and_new_files(native_helpers, tmp_path):
    root = write_bundle(tmp_path / "pet", native_helpers["old"])
    code, report = run_update(native_helpers["exe"], root, tmp_path / "r.json", "--no-launch",
                              "--allow-test-failure-after", "3")
    assert code != 0 and not report["ok"]
    assert (root / "BunnymanDesktopPet.exe").read_bytes() == native_helpers["old"]
    assert (root / "README.md").read_bytes() == b"old guide"
    assert not (root / "_internal/new-file.txt").exists()
    assert (root / "personal.txt").read_bytes() == b"keep me"


@pytest.mark.parametrize("problem", ["runtime", "qt_runtime", "image", "version"])
def test_native_update_rejects_wrong_or_incomplete_installations(native_helpers, tmp_path, problem):
    root = write_bundle(tmp_path / "pet", native_helpers["old"])
    if problem == "runtime":
        (root / "_internal/python313.dll").unlink()
    elif problem == "qt_runtime":
        (root / "_internal/Qt6Core.dll").unlink()
    elif problem == "image":
        (root / "frames/idle.png").unlink()
    else:
        (root / "BunnymanDesktopPet.exe").write_bytes(b"unsupported executable")
    before = (root / "BunnymanDesktopPet.exe").read_bytes()
    code, report = run_update(native_helpers["exe"], root, tmp_path / "r.json", "--no-launch")
    assert code != 0 and not report["ok"]
    assert (root / "BunnymanDesktopPet.exe").read_bytes() == before
    assert (root / "README.md").read_bytes() == b"old guide"


@pytest.mark.parametrize("kind", ["traversal", "bad_hash"])
def test_native_update_rejects_invalid_payload_without_writing(native_helpers, tmp_path, kind):
    root = write_bundle(tmp_path / "pet", native_helpers["old"])
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"leave alone")
    code, report = run_update(native_helpers[kind], root, tmp_path / "r.json", "--no-launch")
    assert code != 0 and not report["ok"]
    assert outside.read_bytes() == b"leave alone"
    assert (root / "README.md").read_bytes() == b"old guide"


def test_native_update_restarts_from_the_original_program_folder(native_helpers, tmp_path):
    root = write_bundle(tmp_path / "pet", native_helpers["old"])
    code, report = run_update(native_helpers["production"], root, tmp_path / "r.json")
    assert code == 0 and report["ok"] and report["launched"], report
    deadline = time.monotonic() + 5
    while not (root / "launched.txt").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert (root / "launched.txt").read_text() == "new version"


def test_native_update_only_closes_processes_in_the_selected_installation(native_helpers, tmp_path):
    target = write_bundle(tmp_path / "pet", native_helpers["old"])
    other = write_bundle(tmp_path / "other", native_helpers["old"])
    processes = [subprocess.Popen([str(folder / "BunnymanDesktopPet.exe")], cwd=folder) for folder in (target, other)]
    try:
        time.sleep(0.8)
        assert all(process.poll() is None for process in processes)
        code, report = run_update(native_helpers["exe"], target, tmp_path / "r.json", "--no-launch")
        assert code == 0 and report["ok"], report
        assert processes[0].poll() is not None
        assert processes[1].poll() is None
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def test_update_form_needs_one_click_and_cannot_close_during_replacement(native_helpers, tmp_path):
    target = write_bundle(tmp_path / "pet", native_helpers["old"])
    harness = tmp_path / "gui.cs"
    harness.write_text(r'''
using System; using System.IO; using System.Reflection; using System.Threading;
using System.ComponentModel; using System.Windows.Forms;
class GuiTest {
 [STAThread] static int Main(string[] args) {
  try {
   Application.EnableVisualStyles();
   var assembly=Assembly.LoadFrom(args[0]);
   var program=assembly.GetType("BunnymanUpdater.UpdaterProgram");
   var flags=BindingFlags.NonPublic|BindingFlags.Public|BindingFlags.Static;
   var manifest=program.GetMethod("LoadEmbeddedManifest",flags).Invoke(null,null);
   var type=program.GetNestedType("UpdaterForm",BindingFlags.NonPublic);
   var form=(Form)Activator.CreateInstance(type,BindingFlags.NonPublic|BindingFlags.Public|BindingFlags.Instance,
       null,new object[]{manifest},null);
   flags=BindingFlags.NonPublic|BindingFlags.Instance;
   var path=(TextBox)type.GetField("targetBox",flags).GetValue(form);
   var update=(Button)type.GetField("updateButton",flags).GetValue(form);
   var browse=(Button)type.GetField("browseButton",flags).GetValue(form);
   var worker=(BackgroundWorker)type.GetField("worker",flags).GetValue(form);
   path.Text=Path.Combine(args[1],"BunnymanDesktopPet.exe");
   worker.DoWork+=(s,e)=>Thread.Sleep(350);
   form.Show(); Application.DoEvents();
   using(var bitmap=new System.Drawing.Bitmap(form.Width,form.Height)) {
       form.DrawToBitmap(bitmap,new System.Drawing.Rectangle(0,0,form.Width,form.Height));
       bitmap.Save(args[2],System.Drawing.Imaging.ImageFormat.Png);
   }
   update.PerformClick();
   if(!worker.IsBusy||browse.Enabled||path.Enabled||update.Enabled) return 2;
   form.Close();
   if(!form.Visible) return 3;
   var until=DateTime.UtcNow.AddSeconds(10);
   while(form.Visible&&DateTime.UtcNow<until){Application.DoEvents();Thread.Sleep(10);}
   if(form.Visible) return 4;
   return 0;
  } catch(Exception e){File.WriteAllText(args[2]+".error",e.ToString());return 5;}
 }
}
''', encoding="utf-8")
    exe = tmp_path / "gui.exe"
    subprocess.run([str(build_updater.compiler_path()), "/nologo", "/target:winexe", "/platform:x64",
                    "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                    f"/out:{exe}", str(harness)], check=True, capture_output=True, timeout=30)
    image = tmp_path / "updater-gui.png"
    result = subprocess.run([str(exe), str(native_helpers["production"]), str(target), str(image)], timeout=20)
    assert result.returncode == 0, image.with_suffix(".png.error").read_text() if image.with_suffix(".png.error").exists() else result.returncode
    assert (target / "BunnymanDesktopPet.exe").read_bytes() == native_helpers["new"]
