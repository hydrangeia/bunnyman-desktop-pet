using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Runtime.InteropServices;

namespace BunnymanUpdater
{
    internal sealed class UpdateFile
    {
        public string Path;
        public string Sha256;
    }

    internal sealed class UpdateManifest
    {
        public string Version;
        public string AppExe;
        public string FullDownloadUrl;
        public List<string> AllowedBaseExeSha256 = new List<string>();
        public List<string> RequiredRuntimeFiles = new List<string>();
        public List<UpdateFile> Files = new List<UpdateFile>();
        public bool TestMode;
    }

    internal sealed class OperationResult
    {
        public bool Ok;
        public string Error;
        public string Target;
        public string BackupPath;
        public List<string> UpdatedFiles = new List<string>();
        public bool Launched;
        public bool ShowDownloadLink;
    }

    internal sealed class ChangeRecord
    {
        public string RelativePath;
        public bool Existed;
    }

    internal sealed class UpdateException : Exception
    {
        public bool ShowDownloadLink;

        public UpdateException(string message, bool showDownloadLink)
            : base(message)
        {
            ShowDownloadLink = showDownloadLink;
        }
    }

    internal static class UpdaterProgram
    {
        private const string ApplicationExe = "BunnymanDesktopPet.exe";
        private const string PayloadResource = "UpdatePayload.zip";
        private const string ManifestResource = "UpdateManifest.json";
        private const int WmClose = 0x0010;
        private const int WmQuit = 0x0012;
        private const long MaxPayloadBytes = 8L * 1024L * 1024L * 1024L;

        private delegate bool EnumWindowsProc(IntPtr window, IntPtr parameter);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll", EntryPoint = "PostThreadMessageW", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern bool PostThreadMessage(uint threadId, uint message, IntPtr wParam, IntPtr lParam);

        [STAThread]
        private static int Main(string[] args)
        {
            if (args != null && args.Length > 0)
                return RunCommandLine(args);

            try
            {
                UpdateManifest manifest = LoadEmbeddedManifest();
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new UpdaterForm(manifest));
                return 0;
            }
            catch (Exception exception)
            {
                MessageBox.Show(
                    "更新助手无法启动。\r\n\r\n" + FriendlyException(exception),
                    "兔人桌宠更新助手",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                return 1;
            }
        }

        private static int RunCommandLine(string[] args)
        {
            string target = null;
            string reportPath = null;
            bool silent = false;
            bool noLaunch = false;
            int failAfter = 0;
            OperationResult result;

            try
            {
                for (int index = 0; index < args.Length; index++)
                {
                    string argument = args[index];
                    if (argument == "--target")
                    {
                        target = RequireArgumentValue(args, ref index, argument);
                    }
                    else if (argument == "--report")
                    {
                        reportPath = RequireArgumentValue(args, ref index, argument);
                    }
                    else if (argument == "--silent")
                    {
                        silent = true;
                    }
                    else if (argument == "--no-launch")
                    {
                        noLaunch = true;
                    }
                    else if (argument == "--allow-test-failure-after")
                    {
                        string raw = RequireArgumentValue(args, ref index, argument);
                        if (!Int32.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out failAfter) || failAfter < 1)
                            throw new UpdateException("--allow-test-failure-after 必须是正整数。", false);
                    }
                    else
                    {
                        throw new UpdateException("无法识别的命令行参数：" + argument, false);
                    }
                }

                if (String.IsNullOrWhiteSpace(target))
                    throw new UpdateException("命令行模式需要 --target <dir>。", false);
                if (!silent)
                    throw new UpdateException("命令行模式必须指定 --silent。", false);

                UpdateManifest manifest = LoadEmbeddedManifest();
                if (failAfter > 0 && (!manifest.TestMode || !noLaunch))
                    throw new UpdateException("故障注入仅允许在 test_mode 更新包且指定 --no-launch 时执行。", false);

                result = ApplyUpdate(target, manifest, !noLaunch, failAfter);
            }
            catch (Exception exception)
            {
                result = new OperationResult();
                result.Ok = false;
                result.Target = target;
                result.Error = FriendlyException(exception);
                UpdateManifest maybeManifest = TryLoadEmbeddedManifest();
                result.ShowDownloadLink = maybeManifest != null && exception is UpdateException && ((UpdateException)exception).ShowDownloadLink;
            }

            if (!String.IsNullOrWhiteSpace(reportPath))
            {
                try
                {
                    WriteReport(reportPath, result);
                }
                catch (Exception exception)
                {
                    Console.Error.WriteLine("无法写入指定的更新报告：" + FriendlyException(exception));
                    return 2;
                }
            }

            return result.Ok ? 0 : 1;
        }

        private static string RequireArgumentValue(string[] args, ref int index, string option)
        {
            if (index + 1 >= args.Length || args[index + 1].StartsWith("--", StringComparison.Ordinal))
                throw new UpdateException(option + " 缺少参数。", false);
            index++;
            return args[index];
        }

        private static UpdateManifest TryLoadEmbeddedManifest()
        {
            try { return LoadEmbeddedManifest(); }
            catch { return null; }
        }

        private static UpdateManifest LoadEmbeddedManifest()
        {
            string json;
            using (Stream stream = OpenEmbeddedResource(ManifestResource))
            using (StreamReader reader = new StreamReader(stream, Encoding.UTF8, true))
                json = reader.ReadToEnd();

            JavaScriptSerializer serializer = new JavaScriptSerializer();
            serializer.MaxJsonLength = Int32.MaxValue;
            object decoded;
            try { decoded = serializer.DeserializeObject(json); }
            catch (Exception exception) { throw new UpdateException("內嵌更新清單格式無效：" + exception.Message, false); }

            IDictionary<string, object> root = decoded as IDictionary<string, object>;
            if (root == null)
                throw new UpdateException("內嵌更新清單不是 JSON 物件。", false);

            UpdateManifest manifest = new UpdateManifest();
            manifest.Version = RequiredString(root, "version");
            manifest.AppExe = RequiredString(root, "app_exe");
            manifest.FullDownloadUrl = RequiredString(root, "full_download_url");
            if (!String.Equals(manifest.AppExe, ApplicationExe, StringComparison.OrdinalIgnoreCase))
                throw new UpdateException("更新清單中的 app_exe 必须是 " + ApplicationExe + "。", false);
            Uri downloadUri;
            if (!Uri.TryCreate(manifest.FullDownloadUrl, UriKind.Absolute, out downloadUri) || downloadUri.Scheme != Uri.UriSchemeHttps)
                throw new UpdateException("更新清單中的完整包链接必须是 HTTPS 地址。", false);

            object allowedValue;
            if (!root.TryGetValue("allowed_base_exe_sha256", out allowedValue))
                throw new UpdateException("更新清单缺少 allowed_base_exe_sha256。", false);
            IList allowed = allowedValue as IList;
            if (allowed == null || allowed.Count == 0)
                throw new UpdateException("allowed_base_exe_sha256 必须包含旧版与当前版程序哈希。", false);
            HashSet<string> allowedHashes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (object value in allowed)
            {
                string hash = value as string;
                if (!IsSha256(hash))
                    throw new UpdateException("allowed_base_exe_sha256 中有无效的 SHA-256。", false);
                if (allowedHashes.Add(hash))
                    manifest.AllowedBaseExeSha256.Add(hash.ToLowerInvariant());
            }

            object runtimeValue;
            if (root.TryGetValue("required_runtime_files", out runtimeValue))
            {
                IList runtimeFiles = runtimeValue as IList;
                if (runtimeFiles == null)
                    throw new UpdateException("required_runtime_files 必须是相对路径字符串数组。", false);
                HashSet<string> requiredPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (object value in runtimeFiles)
                {
                    string rawPath = value as string;
                    if (String.IsNullOrWhiteSpace(rawPath))
                        throw new UpdateException("required_runtime_files 中有无效路径。", false);
                    string path = NormalizeUpdatePath(rawPath);
                    if (!requiredPaths.Add(path))
                        throw new UpdateException("required_runtime_files 包含重复路径：" + path, false);
                    manifest.RequiredRuntimeFiles.Add(path);
                }
                if (manifest.RequiredRuntimeFiles.Count == 0)
                    throw new UpdateException("required_runtime_files 不能是空数组。", false);
            }

            object filesValue;
            if (!root.TryGetValue("files", out filesValue))
                throw new UpdateException("更新清单缺少 files。", false);
            IList files = filesValue as IList;
            if (files == null || files.Count == 0)
                throw new UpdateException("更新清单 files 必须包含文件及 SHA-256。", false);
            HashSet<string> listedPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (object fileValue in files)
            {
                IDictionary<string, object> fileObject = fileValue as IDictionary<string, object>;
                if (fileObject == null)
                    throw new UpdateException("更新清单 files 中有无效项目。", false);
                string path = RequiredString(fileObject, "path");
                string normalized = NormalizeUpdatePath(path);
                string hash = RequiredString(fileObject, "sha256");
                if (!IsSha256(hash))
                    throw new UpdateException("更新清单文件哈希无效：" + path, false);
                if (!listedPaths.Add(normalized))
                    throw new UpdateException("更新清单包含重复路径：" + path, false);
                manifest.Files.Add(new UpdateFile { Path = normalized, Sha256 = hash.ToLowerInvariant() });
            }

            UpdateFile exeFile = manifest.Files.FirstOrDefault(
                item => String.Equals(item.Path, ApplicationExe, StringComparison.OrdinalIgnoreCase));
            if (exeFile == null || !allowedHashes.Contains(exeFile.Sha256))
                throw new UpdateException("更新清单必须包含新程序文件，且其哈希应列在允许版本中。", false);

            object testMode;
            if (root.TryGetValue("test_mode", out testMode) && testMode is bool)
                manifest.TestMode = (bool)testMode;
            return manifest;
        }

        private static string RequiredString(IDictionary<string, object> source, string key)
        {
            object value;
            string text = source.TryGetValue(key, out value) ? value as string : null;
            if (String.IsNullOrWhiteSpace(text))
                throw new UpdateException("更新清单缺少有效的 " + key + "。", false);
            return text;
        }

        private static Stream OpenEmbeddedResource(string shortName)
        {
            System.Reflection.Assembly assembly = System.Reflection.Assembly.GetExecutingAssembly();
            string exact = null;
            foreach (string name in assembly.GetManifestResourceNames())
            {
                if (String.Equals(name, shortName, StringComparison.Ordinal) || name.EndsWith("." + shortName, StringComparison.Ordinal))
                {
                    if (exact != null)
                        throw new UpdateException("更新助手中存在重复资源：" + shortName, false);
                    exact = name;
                }
            }
            if (exact == null)
                throw new UpdateException("更新助手缺少內嵌资源：" + shortName, false);
            Stream stream = assembly.GetManifestResourceStream(exact);
            if (stream == null)
                throw new UpdateException("无法读取內嵌资源：" + shortName, false);
            return stream;
        }

        private static string NormalizeUpdatePath(string raw)
        {
            if (String.IsNullOrWhiteSpace(raw) || raw.IndexOf('\\') >= 0 || raw.StartsWith("/", StringComparison.Ordinal) || raw.IndexOf(':') >= 0)
                throw new UpdateException("更新清单路径必须是安全的正斜线相对路径：" + raw, false);
            string[] parts = raw.Split('/');
            for (int index = 0; index < parts.Length; index++)
            {
                string part = parts[index];
                if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".", StringComparison.Ordinal) || part.EndsWith(" ", StringComparison.Ordinal))
                    throw new UpdateException("更新清单包含不安全路径：" + raw, false);
                if (part.StartsWith(".bunnyman-update-", StringComparison.OrdinalIgnoreCase))
                    throw new UpdateException("更新文件不能覆盖更新助手的暂存目录：" + raw, false);
                if (part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || IsReservedWindowsName(part))
                    throw new UpdateException("更新清单包含 Windows 不支持的路径：" + raw, false);
            }
            return String.Join("/", parts);
        }

        private static string NormalizeLegacyAssetPath(string raw)
        {
            if (String.IsNullOrWhiteSpace(raw))
                throw NeedFullPackage("资源清单中有空路径。");
            return NormalizePathParts(raw.Replace('\\', '/'), raw);
        }

        private static string NormalizeZipPath(string raw, bool isDirectory)
        {
            if (String.IsNullOrWhiteSpace(raw) || raw.IndexOf('\\') >= 0)
                throw new UpdateException("更新包包含空路径或反斜线路径。", false);
            string value = raw;
            if (isDirectory)
            {
                if (!value.EndsWith("/", StringComparison.Ordinal))
                    throw new UpdateException("更新包目录路径格式无效：" + raw, false);
                value = value.Substring(0, value.Length - 1);
            }
            else if (value.EndsWith("/", StringComparison.Ordinal))
            {
                throw new UpdateException("更新包文件路径格式无效：" + raw, false);
            }
            return NormalizePathParts(value, raw);
        }

        private static string NormalizePathParts(string slashPath, string original)
        {
            if (slashPath.Length == 0 || slashPath.StartsWith("/", StringComparison.Ordinal) || slashPath.IndexOf(':') >= 0)
                throw new UpdateException("发现绝对路径：" + original, false);
            string[] parts = slashPath.Split('/');
            for (int index = 0; index < parts.Length; index++)
            {
                string part = parts[index];
                if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".", StringComparison.Ordinal) || part.EndsWith(" ", StringComparison.Ordinal))
                    throw new UpdateException("发现不安全的相对路径：" + original, false);
                if (part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || IsReservedWindowsName(part))
                    throw new UpdateException("发现 Windows 不支持的路径：" + original, false);
            }
            return String.Join("/", parts);
        }

        private static bool IsReservedWindowsName(string name)
        {
            string stem = name.Split('.')[0].TrimEnd(' ', '.').ToUpperInvariant();
            if (stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL") return true;
            for (int index = 1; index <= 9; index++)
            {
                if (stem == "COM" + index.ToString(CultureInfo.InvariantCulture) || stem == "LPT" + index.ToString(CultureInfo.InvariantCulture))
                    return true;
            }
            return false;
        }

        private static bool IsSha256(string value)
        {
            if (value == null || value.Length != 64) return false;
            for (int index = 0; index < value.Length; index++)
            {
                char current = value[index];
                if (!((current >= '0' && current <= '9') || (current >= 'a' && current <= 'f') || (current >= 'A' && current <= 'F')))
                    return false;
            }
            return true;
        }

        private static UpdateException NeedFullPackage(string message)
        {
            return new UpdateException("旧程序资源不完整，请下载完整包。" + message, true);
        }

        private static OperationResult ApplyUpdate(string targetInput, UpdateManifest manifest, bool launch, int failAfter)
        {
            OperationResult result = new OperationResult();
            result.Target = targetInput;
            string target = null;
            string stage = null;
            List<ChangeRecord> changes = new List<ChangeRecord>();
            try
            {
                target = ResolveTargetDirectory(targetInput);
                result.Target = target;
                ValidateTarget(target, manifest);
                stage = CreateUniqueDirectory(target, ".bunnyman-update-stage-");
                ExtractAndVerifyPayload(stage, manifest);

                CloseMatchingApplicationProcesses(Path.Combine(target, ApplicationExe));
                result.BackupPath = CreateUniqueDirectory(target, ".bunnyman-update-backup-");
                BackupFiles(target, result.BackupPath, manifest.Files);

                int copied = 0;
                foreach (UpdateFile file in manifest.Files)
                {
                    string destination = CombineUnderRoot(target, file.Path);
                    string source = CombineUnderRoot(Path.Combine(stage, "files"), file.Path);
                    EnsureNoReparsePointChain(Path.GetDirectoryName(destination), false);
                    EnsureNoReparsePointChain(destination, true);
                    EnsureDirectoryPath(Path.GetDirectoryName(destination), target);

                    bool existed = File.Exists(destination);
                    changes.Add(new ChangeRecord { RelativePath = file.Path, Existed = existed });
                    File.Copy(source, destination, true);
                    copied++;
                    result.UpdatedFiles.Add(file.Path);
                    if (failAfter > 0 && copied == failAfter)
                        throw new UpdateException("测试模式注入失败，用于验证文件回滚。", false);
                }

                result.Ok = true;
                result.Error = null;
            }
            catch (Exception exception)
            {
                result.Ok = false;
                result.Error = FriendlyException(exception);
                result.ShowDownloadLink = exception is UpdateException && ((UpdateException)exception).ShowDownloadLink;
                if (changes.Count > 0 && target != null && !String.IsNullOrWhiteSpace(result.BackupPath))
                {
                    string rollbackError = RollBack(target, result.BackupPath, changes);
                    if (!String.IsNullOrWhiteSpace(rollbackError))
                        result.Error = result.Error + "\r\n回滚未能完全完成：" + rollbackError + "。备份仍保留在：" + result.BackupPath;
                    else
                        result.UpdatedFiles.Clear();
                }
            }
            finally
            {
                if (!String.IsNullOrWhiteSpace(stage))
                    TryDeleteDirectory(stage, target);
            }

            if (result.Ok && launch)
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = Path.Combine(target, ApplicationExe),
                        WorkingDirectory = target,
                        UseShellExecute = true
                    });
                    result.Launched = true;
                }
                catch (Exception exception)
                {
                    result.Error = "更新已完成，但无法自动重新启动桌宠：" + FriendlyException(exception);
                }
            }
            return result;
        }

        private static string ResolveTargetDirectory(string input)
        {
            if (String.IsNullOrWhiteSpace(input))
                throw new UpdateException("请选择旧版桌宠程序或其所在文件夹。", false);
            string full = Path.GetFullPath(input.Trim().Trim('"'));
            if (Directory.Exists(full)) return full;
            if (File.Exists(full))
            {
                if (!String.Equals(Path.GetFileName(full), ApplicationExe, StringComparison.OrdinalIgnoreCase))
                    throw new UpdateException("请选择 " + ApplicationExe + "，不要选择其他程序。", false);
                return Path.GetDirectoryName(full);
            }
            throw new UpdateException("找不到所选文件或文件夹：" + full, false);
        }

        private static void ValidateTarget(string target, UpdateManifest manifest)
        {
            if (!Directory.Exists(target))
                throw new UpdateException("所选目录不存在。", false);
            EnsureNoReparsePointChain(target, false);
            string root = Path.GetPathRoot(target);
            if (String.Equals(TrimEndingSeparator(target), TrimEndingSeparator(root), StringComparison.OrdinalIgnoreCase))
                throw new UpdateException("不能将磁盘根目录作为桌宠安装目录。", false);

            string exePath = Path.Combine(target, manifest.AppExe);
            string runtimePath = Path.Combine(target, "_internal", "python313.dll");
            string manifestPath = Path.Combine(target, "manifest.json");
            string framesPath = Path.Combine(target, "frames");
            if (!File.Exists(exePath)) throw NeedFullPackage("缺少 " + manifest.AppExe + "。");
            if (!File.Exists(runtimePath)) throw NeedFullPackage("缺少 _internal/python313.dll。");
            if (!File.Exists(manifestPath)) throw NeedFullPackage("缺少 manifest.json。");
            if (!Directory.Exists(framesPath)) throw NeedFullPackage("缺少 frames 文件夹。");
            EnsureNoReparsePointChain(exePath, true);
            EnsureNoReparsePointChain(runtimePath, true);
            EnsureNoReparsePointChain(manifestPath, true);
            EnsureNoReparsePointChain(framesPath, false);

            foreach (string runtimeRelative in manifest.RequiredRuntimeFiles)
            {
                string requiredPath = CombineUnderRoot(target, runtimeRelative);
                EnsureNoReparsePointChain(requiredPath, true);
                if (!File.Exists(requiredPath))
                    throw NeedFullPackage("缺少运行组件 " + runtimeRelative + "。");
            }

            string installedHash = ComputeSha256(exePath);
            if (!manifest.AllowedBaseExeSha256.Contains(installedHash, StringComparer.OrdinalIgnoreCase))
                throw new UpdateException("此版本桌宠不适用于当前更新包。请下载完整包后重新安装。", true);

            ValidateInstalledManifestAssets(target, manifestPath);
            foreach (UpdateFile file in manifest.Files)
            {
                string destination = CombineUnderRoot(target, file.Path);
                EnsureNoReparsePointChain(Path.GetDirectoryName(destination), false);
                EnsureNoReparsePointChain(destination, true);
                if (Directory.Exists(destination))
                    throw new UpdateException("更新目标路径已被同名文件夹占用：" + file.Path, false);
            }
        }

        private static void ValidateInstalledManifestAssets(string target, string manifestPath)
        {
            object decoded;
            try
            {
                JavaScriptSerializer serializer = new JavaScriptSerializer();
                serializer.MaxJsonLength = Int32.MaxValue;
                decoded = serializer.DeserializeObject(File.ReadAllText(manifestPath, Encoding.UTF8));
            }
            catch (Exception exception)
            {
                throw NeedFullPackage("manifest.json 无法读取或格式无效：" + exception.Message);
            }
            IDictionary<string, object> root = decoded as IDictionary<string, object>;
            if (root == null)
                throw NeedFullPackage("manifest.json 不是有效对象。");

            List<string> references = new List<string>();
            object animations;
            if (root.TryGetValue("animations", out animations)) CollectNamedPaths(animations, "frames", references);
            object effects;
            if (root.TryGetValue("effects", out effects)) CollectNamedPaths(effects, "frames", references);
            object props;
            if (root.TryGetValue("props", out props)) CollectNamedPaths(props, "path", references);
            if (references.Count == 0)
                throw NeedFullPackage("manifest.json 没有动画、特效或道具资源引用。");

            HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string reference in references)
            {
                string relative;
                try { relative = NormalizeLegacyAssetPath(reference); }
                catch (UpdateException exception) { throw NeedFullPackage(exception.Message); }
                if (!seen.Add(relative)) continue;
                string extension = Path.GetExtension(relative);
                if (!String.Equals(extension, ".png", StringComparison.OrdinalIgnoreCase) &&
                    !String.Equals(extension, ".webp", StringComparison.OrdinalIgnoreCase))
                    throw NeedFullPackage("资源格式不是 PNG/WebP：" + relative);
                string assetPath = CombineUnderRoot(target, relative);
                EnsureNoReparsePointChain(assetPath, true);
                if (!File.Exists(assetPath))
                    throw NeedFullPackage("缺少资源文件 " + relative + "。");
            }
        }

        private static void CollectNamedPaths(object node, string keyName, List<string> output)
        {
            IDictionary<string, object> dictionary = node as IDictionary<string, object>;
            if (dictionary != null)
            {
                foreach (KeyValuePair<string, object> pair in dictionary)
                {
                    if (String.Equals(pair.Key, keyName, StringComparison.OrdinalIgnoreCase))
                        CollectStringValues(pair.Value, output);
                    else
                        CollectNamedPaths(pair.Value, keyName, output);
                }
                return;
            }
            IList list = node as IList;
            if (list != null)
            {
                foreach (object item in list) CollectNamedPaths(item, keyName, output);
            }
        }

        private static void CollectStringValues(object node, List<string> output)
        {
            string value = node as string;
            if (value != null)
            {
                output.Add(value);
                return;
            }
            IDictionary<string, object> dictionary = node as IDictionary<string, object>;
            if (dictionary != null)
            {
                foreach (object child in dictionary.Values) CollectStringValues(child, output);
                return;
            }
            IList list = node as IList;
            if (list != null)
            {
                foreach (object child in list) CollectStringValues(child, output);
            }
        }

        private static string CreateUniqueDirectory(string target, string prefix)
        {
            for (int attempt = 0; attempt < 5; attempt++)
            {
                string path = Path.Combine(target, prefix + Guid.NewGuid().ToString("N"));
                try
                {
                    Directory.CreateDirectory(path);
                    EnsureNoReparsePointChain(path, false);
                    return path;
                }
                catch (IOException)
                {
                    if (attempt == 4) throw;
                }
            }
            throw new IOException("无法创建唯一的更新暂存目录。");
        }

        private static void ExtractAndVerifyPayload(string stage, UpdateManifest manifest)
        {
            string zipPath = Path.Combine(stage, "UpdatePayload.zip");
            using (Stream resource = OpenEmbeddedResource(PayloadResource))
            using (FileStream output = new FileStream(zipPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                CopyStream(resource, output);

            string filesRoot = Path.Combine(stage, "files");
            Directory.CreateDirectory(filesRoot);
            EnsureNoReparsePointChain(filesRoot, false);
            Dictionary<string, UpdateFile> expected = new Dictionary<string, UpdateFile>(StringComparer.OrdinalIgnoreCase);
            foreach (UpdateFile file in manifest.Files) expected.Add(file.Path, file);
            HashSet<string> seenEntries = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            HashSet<string> seenFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            long totalBytes = 0;

            using (FileStream zipFile = new FileStream(zipPath, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (ZipArchive archive = new ZipArchive(zipFile, ZipArchiveMode.Read, false))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    bool isDirectory = entry.FullName.EndsWith("/", StringComparison.Ordinal);
                    string relative = NormalizeZipPath(entry.FullName, isDirectory);
                    if (!seenEntries.Add(relative))
                        throw new UpdateException("更新包包含重复路径：" + relative, false);
                    int unixType = (entry.ExternalAttributes >> 16) & 0xF000;
                    if (unixType == 0xA000 || (entry.ExternalAttributes & (int)FileAttributes.ReparsePoint) != 0)
                        throw new UpdateException("更新包不能包含符号链接或重解析点：" + relative, false);

                    if (isDirectory)
                    {
                        bool parentOfListedFile = manifest.Files.Any(
                            file => file.Path.StartsWith(relative + "/", StringComparison.OrdinalIgnoreCase));
                        if (!parentOfListedFile)
                            throw new UpdateException("更新包含有未列入清单的目录：" + relative, false);
                        continue;
                    }

                    UpdateFile expectedFile;
                    if (!expected.TryGetValue(relative, out expectedFile))
                        throw new UpdateException("更新包含有未列入清单的文件：" + relative, false);
                    if (!seenFiles.Add(relative))
                        throw new UpdateException("更新包包含重复文件：" + relative, false);
                    totalBytes += entry.Length;
                    if (entry.Length < 0 || totalBytes > MaxPayloadBytes)
                        throw new UpdateException("更新包解压后体积超过安全限制。", false);

                    string destination = CombineUnderRoot(filesRoot, expectedFile.Path);
                    EnsureDirectoryPath(Path.GetDirectoryName(destination), filesRoot);
                    EnsureNoReparsePointChain(Path.GetDirectoryName(destination), false);
                    using (Stream input = entry.Open())
                    using (FileStream fileOutput = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    {
                        CopyStream(input, fileOutput);
                    }
                    FileInfo extracted = new FileInfo(destination);
                    if (extracted.Length != entry.Length)
                        throw new UpdateException("更新包文件长度校验失败：" + relative, false);
                    string hash = ComputeSha256(destination);
                    if (!String.Equals(hash, expectedFile.Sha256, StringComparison.OrdinalIgnoreCase))
                        throw new UpdateException("更新包 SHA-256 校验失败：" + relative, false);
                }
            }

            foreach (UpdateFile file in manifest.Files)
            {
                if (!seenFiles.Contains(file.Path))
                    throw new UpdateException("更新包缺少清单文件：" + file.Path, false);
            }
        }

        private static void BackupFiles(string target, string backup, IList<UpdateFile> files)
        {
            foreach (UpdateFile file in files)
            {
                string source = CombineUnderRoot(target, file.Path);
                EnsureNoReparsePointChain(source, true);
                if (!File.Exists(source)) continue;
                if (Directory.Exists(source))
                    throw new UpdateException("更新目标位置存在同名文件夹：" + file.Path, false);
                string backupFile = CombineUnderRoot(backup, file.Path);
                EnsureDirectoryPath(Path.GetDirectoryName(backupFile), backup);
                EnsureNoReparsePointChain(Path.GetDirectoryName(backupFile), false);
                File.Copy(source, backupFile, false);
            }
        }

        private static string RollBack(string target, string backup, IList<ChangeRecord> changes)
        {
            List<string> failures = new List<string>();
            for (int index = changes.Count - 1; index >= 0; index--)
            {
                ChangeRecord change = changes[index];
                try
                {
                    string destination = CombineUnderRoot(target, change.RelativePath);
                    EnsureNoReparsePointChain(Path.GetDirectoryName(destination), false);
                    EnsureNoReparsePointChain(destination, true);
                    if (change.Existed)
                    {
                        string backupFile = CombineUnderRoot(backup, change.RelativePath);
                        if (!File.Exists(backupFile))
                            throw new IOException("备份文件不存在：" + change.RelativePath);
                        EnsureDirectoryPath(Path.GetDirectoryName(destination), target);
                        File.Copy(backupFile, destination, true);
                    }
                    else if (File.Exists(destination))
                    {
                        File.Delete(destination);
                    }
                }
                catch (Exception exception)
                {
                    failures.Add(change.RelativePath + "（" + exception.Message + "）");
                }
            }
            return failures.Count == 0 ? null : String.Join("；", failures.ToArray());
        }

        private static void EnsureDirectoryPath(string directory, string root)
        {
            string fullRoot = TrimEndingSeparator(Path.GetFullPath(root));
            string fullDirectory = Path.GetFullPath(directory);
            string rootWithSeparator = AddEndingSeparator(fullRoot);
            if (String.Equals(fullDirectory, fullRoot, StringComparison.OrdinalIgnoreCase))
            {
                EnsureNoReparsePointChain(fullRoot, false);
                return;
            }
            if (!fullDirectory.StartsWith(rootWithSeparator, StringComparison.OrdinalIgnoreCase))
                throw new UpdateException("拒绝在安装目录之外创建文件夹：" + fullDirectory, false);
            string relative = fullDirectory.Substring(rootWithSeparator.Length);
            string current = fullRoot;
            EnsureNoReparsePointChain(current, false);
            if (relative.Length == 0) return;
            string[] parts = relative.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            foreach (string part in parts)
            {
                if (part.Length == 0) continue;
                current = Path.Combine(current, part);
                if (File.Exists(current))
                    throw new UpdateException("更新路径的文件夹层级被文件占用：" + current, false);
                if (!Directory.Exists(current)) Directory.CreateDirectory(current);
                EnsureNoReparsePointChain(current, false);
            }
        }

        private static string CombineUnderRoot(string root, string relative)
        {
            string fullRoot = Path.GetFullPath(root);
            string windowsRelative = relative.Replace('/', Path.DirectorySeparatorChar);
            string candidate = Path.GetFullPath(Path.Combine(fullRoot, windowsRelative));
            string rootPrefix = AddEndingSeparator(TrimEndingSeparator(fullRoot));
            if (!candidate.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase))
                throw new UpdateException("路径超出允许目录：" + relative, false);
            return candidate;
        }

        private static void EnsureNoReparsePointChain(string path, bool leafIsFile)
        {
            string full = Path.GetFullPath(path);
            string root = Path.GetPathRoot(full);
            if (String.IsNullOrEmpty(root))
                throw new UpdateException("无法确认路径所在磁盘：" + full, false);
            string current = root;
            string trimmed = full.Substring(root.Length).Trim(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            string[] parts = trimmed.Length == 0 ? new string[0] : trimmed.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            for (int index = 0; index < parts.Length; index++)
            {
                current = Path.Combine(current, parts[index]);
                FileAttributes attributes;
                try { attributes = File.GetAttributes(current); }
                catch (FileNotFoundException) { break; }
                catch (DirectoryNotFoundException) { break; }
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                    throw new UpdateException("为避免写入链接或联接目录，更新已停止：" + current, false);
                bool isLast = index == parts.Length - 1;
                if (!isLast && (attributes & FileAttributes.Directory) == 0)
                    throw new UpdateException("路径层级中有文件占用了文件夹位置：" + current, false);
                if (isLast && !leafIsFile && (attributes & FileAttributes.Directory) == 0)
                    throw new UpdateException("预期的文件夹不存在：" + current, false);
            }
        }

        private static string TrimEndingSeparator(string path)
        {
            string root = Path.GetPathRoot(path);
            string result = path;
            while (result.Length > (root == null ? 0 : root.Length) &&
                (result.EndsWith(Path.DirectorySeparatorChar.ToString(), StringComparison.Ordinal) ||
                 result.EndsWith(Path.AltDirectorySeparatorChar.ToString(), StringComparison.Ordinal)))
                result = result.Substring(0, result.Length - 1);
            return result;
        }

        private static string AddEndingSeparator(string path)
        {
            if (path.EndsWith(Path.DirectorySeparatorChar.ToString(), StringComparison.Ordinal) ||
                path.EndsWith(Path.AltDirectorySeparatorChar.ToString(), StringComparison.Ordinal)) return path;
            return path + Path.DirectorySeparatorChar;
        }

        private static void TryDeleteDirectory(string directory, string allowedRoot)
        {
            try
            {
                if (String.IsNullOrWhiteSpace(directory) || !Directory.Exists(directory)) return;
                EnsureNoReparsePointChain(directory, false);
                string fullRoot = TrimEndingSeparator(Path.GetFullPath(allowedRoot));
                string full = Path.GetFullPath(directory);
                if (!full.StartsWith(AddEndingSeparator(fullRoot), StringComparison.OrdinalIgnoreCase)) return;
                Directory.Delete(full, true);
            }
            catch { }
        }

        private static string ComputeSha256(string path)
        {
            using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (SHA256 algorithm = SHA256.Create())
            {
                byte[] hash = algorithm.ComputeHash(stream);
                StringBuilder builder = new StringBuilder(hash.Length * 2);
                foreach (byte value in hash) builder.Append(value.ToString("x2", CultureInfo.InvariantCulture));
                return builder.ToString();
            }
        }

        private static void CopyStream(Stream input, Stream output)
        {
            byte[] buffer = new byte[1024 * 64];
            int read;
            while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
                output.Write(buffer, 0, read);
        }

        private static void CloseMatchingApplicationProcesses(string expectedExePath)
        {
            string expected = Path.GetFullPath(expectedExePath);
            Process[] candidates = Process.GetProcessesByName(Path.GetFileNameWithoutExtension(ApplicationExe));
            List<Process> matches = new List<Process>();
            List<Process> unresolved = new List<Process>();
            foreach (Process process in candidates)
            {
                if (process.Id == Process.GetCurrentProcess().Id)
                {
                    process.Dispose();
                    continue;
                }
                try
                {
                    string processPath = process.MainModule.FileName;
                    if (String.Equals(Path.GetFullPath(processPath), expected, StringComparison.OrdinalIgnoreCase))
                        matches.Add(process);
                    else
                        process.Dispose();
                }
                catch (Exception)
                {
                    bool exited = false;
                    try { exited = process.HasExited; }
                    catch { }
                    if (exited)
                        process.Dispose();
                    else
                        unresolved.Add(process);
                }
            }
            if (unresolved.Count > 0)
            {
                foreach (Process process in matches) process.Dispose();
                foreach (Process process in unresolved) process.Dispose();
                throw new UpdateException("无法确认某个同名兔人桌宠进程的安装路径。请先手动退出兔人桌宠，再重新更新；更新助手不会结束无法确认路径的进程。", false);
            }
            if (matches.Count == 0)
            {
                return;
            }

            DateTime deadline = DateTime.UtcNow.AddSeconds(8);
            foreach (Process process in matches)
            {
                try
                {
                    if (!process.HasExited)
                    {
                        process.CloseMainWindow();
                        RequestWindowsClose(process.Id);
                    }
                }
                catch { }
            }

            while (DateTime.UtcNow < deadline)
            {
                bool anyRunning = false;
                foreach (Process process in matches)
                {
                    try
                    {
                        process.Refresh();
                        if (!process.HasExited) anyRunning = true;
                    }
                    catch { }
                }
                if (!anyRunning)
                {
                    foreach (Process process in matches) process.Dispose();
                    return;
                }
                Thread.Sleep(100);
            }

            List<int> stillRunning = new List<int>();
            foreach (Process process in matches)
            {
                try
                {
                    process.Refresh();
                    if (!process.HasExited) stillRunning.Add(process.Id);
                }
                catch { }
                process.Dispose();
            }
            if (stillRunning.Count > 0)
                throw new UpdateException("目标目录的桌宠仍在运行。请先手动退出该桌宠，再重新更新。更新助手不会强制结束进程。", false);
        }

        private static void RequestWindowsClose(int processId)
        {
            HashSet<uint> threadIds = new HashSet<uint>();
            EnumWindows(delegate(IntPtr window, IntPtr parameter)
            {
                uint owner;
                uint threadId = GetWindowThreadProcessId(window, out owner);
                if (owner == (uint)processId)
                {
                    if (threadId != 0) threadIds.Add(threadId);
                    PostMessage(window, WmClose, IntPtr.Zero, IntPtr.Zero);
                }
                return true;
            }, IntPtr.Zero);
            foreach (uint threadId in threadIds)
                PostThreadMessage(threadId, WmQuit, IntPtr.Zero, IntPtr.Zero);
        }

        private static string FriendlyException(Exception exception)
        {
            if (exception is UpdateException) return exception.Message;
            if (exception is UnauthorizedAccessException) return "没有权限访问所选安装目录。请把桌宠安装在当前用户可写的位置后重试。";
            if (exception is IOException) return "文件操作失败：" + exception.Message;
            if (exception is InvalidDataException) return "更新包无效或已损坏：" + exception.Message;
            return exception.Message;
        }

        private static void WriteReport(string path, OperationResult result)
        {
            string full = Path.GetFullPath(path);
            string parent = Path.GetDirectoryName(full);
            if (!String.IsNullOrEmpty(parent) && !Directory.Exists(parent)) Directory.CreateDirectory(parent);
            Dictionary<string, object> report = new Dictionary<string, object>();
            report["ok"] = result.Ok;
            report["error"] = result.Error;
            report["target"] = result.Target;
            report["backup_path"] = result.BackupPath;
            report["updated_files"] = result.UpdatedFiles;
            report["launched"] = result.Launched;
            JavaScriptSerializer serializer = new JavaScriptSerializer();
            serializer.MaxJsonLength = Int32.MaxValue;
            File.WriteAllText(full, serializer.Serialize(report), new UTF8Encoding(false));
        }

        private static string DefaultTargetCandidate()
        {
            string baseDirectory = AppDomain.CurrentDomain.BaseDirectory;
            string localExe = Path.Combine(baseDirectory, ApplicationExe);
            if (File.Exists(localExe)) return localExe;

            foreach (Process process in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(ApplicationExe)))
            {
                try
                {
                    string path = process.MainModule.FileName;
                    if (String.Equals(Path.GetFileName(path), ApplicationExe, StringComparison.OrdinalIgnoreCase))
                        return path;
                }
                catch { }
                finally { process.Dispose(); }
            }
            return String.Empty;
        }

        private sealed class UpdaterForm : Form
        {
            private readonly UpdateManifest manifest;
            private readonly TextBox targetBox;
            private readonly Button browseButton;
            private readonly Label versionLabel;
            private readonly Label statusLabel;
            private readonly LinkLabel downloadLink;
            private readonly Button updateButton;
            private readonly ProgressBar progress;
            private readonly BackgroundWorker worker;
            private bool allowCloseAfterWorker;

            public UpdaterForm(UpdateManifest updateManifest)
            {
                manifest = updateManifest;
                Text = "兔人桌宠更新助手";
                StartPosition = FormStartPosition.CenterScreen;
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false;
                MinimizeBox = true;
                ClientSize = new System.Drawing.Size(590, 250);

                Label intro = new Label();
                intro.Text = "选择已安装的兔人桌宠程序。更新前会检查资源并备份将被覆盖的文件。";
                intro.AutoSize = false;
                intro.SetBounds(18, 16, 552, 34);
                Controls.Add(intro);

                Label targetLabel = new Label();
                targetLabel.Text = "原程序：";
                targetLabel.SetBounds(18, 61, 78, 24);
                targetLabel.TextAlign = System.Drawing.ContentAlignment.MiddleLeft;
                Controls.Add(targetLabel);

                targetBox = new TextBox();
                targetBox.SetBounds(98, 61, 382, 24);
                targetBox.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
                Controls.Add(targetBox);

                browseButton = new Button();
                browseButton.Text = "选择…";
                browseButton.SetBounds(489, 59, 80, 28);
                browseButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
                browseButton.Click += BrowseClicked;
                Controls.Add(browseButton);

                versionLabel = new Label();
                versionLabel.Text = "可更新到版本 " + manifest.Version;
                versionLabel.SetBounds(18, 98, 552, 24);
                Controls.Add(versionLabel);

                statusLabel = new Label();
                statusLabel.Text = "确认桌宠已安装在所选目录后，点击“更新并重启”。";
                statusLabel.SetBounds(18, 127, 552, 40);
                statusLabel.AutoEllipsis = true;
                Controls.Add(statusLabel);

                downloadLink = new LinkLabel();
                downloadLink.Text = "首次使用？下载完整包";
                downloadLink.LinkBehavior = LinkBehavior.HoverUnderline;
                downloadLink.SetBounds(18, 179, 200, 24);
                downloadLink.Visible = true;
                downloadLink.LinkClicked += DownloadLinkClicked;
                Controls.Add(downloadLink);

                progress = new ProgressBar();
                progress.Style = ProgressBarStyle.Marquee;
                progress.MarqueeAnimationSpeed = 28;
                progress.SetBounds(160, 180, 235, 20);
                progress.Visible = false;
                Controls.Add(progress);

                updateButton = new Button();
                updateButton.Text = "更新并重启";
                updateButton.SetBounds(423, 176, 146, 32);
                updateButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
                updateButton.Click += UpdateClicked;
                Controls.Add(updateButton);
                AcceptButton = updateButton;

                worker = new BackgroundWorker();
                worker.DoWork += WorkerDoWork;
                worker.RunWorkerCompleted += WorkerCompleted;
                FormClosing += FormClosingWhileUpdating;

                string candidate = DefaultTargetCandidate();
                if (!String.IsNullOrEmpty(candidate)) targetBox.Text = candidate;
            }

            private void BrowseClicked(object sender, EventArgs eventArgs)
            {
                using (OpenFileDialog dialog = new OpenFileDialog())
                {
                    dialog.Title = "选择兔人桌宠程序";
                    dialog.Filter = "兔人桌宠程序 (BunnymanDesktopPet.exe)|BunnymanDesktopPet.exe|可执行文件 (*.exe)|*.exe";
                    dialog.CheckFileExists = true;
                    dialog.Multiselect = false;
                    if (File.Exists(targetBox.Text)) dialog.FileName = targetBox.Text;
                    if (dialog.ShowDialog(this) == DialogResult.OK) targetBox.Text = dialog.FileName;
                }
            }

            private void UpdateClicked(object sender, EventArgs eventArgs)
            {
                if (String.IsNullOrWhiteSpace(targetBox.Text))
                {
                    MessageBox.Show(this, "请先选择 BunnymanDesktopPet.exe 或其所在文件夹。", Text,
                        MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }
                SetBusy(true);
                statusLabel.Text = "正在检查文件、暂存更新并创建备份，请稍候…";
                downloadLink.Visible = false;
                worker.RunWorkerAsync(targetBox.Text);
            }

            private void SetBusy(bool busy)
            {
                updateButton.Enabled = !busy;
                targetBox.Enabled = !busy;
                browseButton.Enabled = !busy;
                progress.Visible = busy;
            }

            private void FormClosingWhileUpdating(object sender, FormClosingEventArgs eventArgs)
            {
                if (worker.IsBusy && !allowCloseAfterWorker)
                {
                    eventArgs.Cancel = true;
                    statusLabel.Text = "正在更新，请稍候…";
                }
            }

            private void WorkerDoWork(object sender, DoWorkEventArgs eventArgs)
            {
                eventArgs.Result = ApplyUpdate((string)eventArgs.Argument, manifest, true, 0);
            }

            private void WorkerCompleted(object sender, RunWorkerCompletedEventArgs eventArgs)
            {
                SetBusy(false);
                if (eventArgs.Error != null)
                {
                    statusLabel.Text = "更新没有完成。";
                    MessageBox.Show(this, "更新没有完成：\r\n\r\n" + FriendlyException(eventArgs.Error), Text,
                        MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                OperationResult result = eventArgs.Result as OperationResult;
                if (result == null)
                {
                    statusLabel.Text = "更新没有完成。";
                    return;
                }
                if (result.ShowDownloadLink) downloadLink.Visible = true;
                if (!result.Ok)
                {
                    statusLabel.Text = result.Error;
                    MessageBox.Show(this, result.Error, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                if (result.Launched)
                {
                    statusLabel.Text = "更新完成，桌宠已重新启动。备份保存在：" + result.BackupPath;
                    allowCloseAfterWorker = true;
                    Close();
                    return;
                }
                statusLabel.Text = result.Error ?? ("更新完成。备份保存在：" + result.BackupPath);
                MessageBox.Show(this, statusLabel.Text, Text, MessageBoxButtons.OK,
                    String.IsNullOrEmpty(result.Error) ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
                allowCloseAfterWorker = true;
                Close();
            }

            private void DownloadLinkClicked(object sender, LinkLabelLinkClickedEventArgs eventArgs)
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = manifest.FullDownloadUrl,
                        UseShellExecute = true
                    });
                    downloadLink.LinkVisited = true;
                }
                catch (Exception exception)
                {
                    MessageBox.Show(this, "无法打开完整包下载链接：\r\n" + FriendlyException(exception), Text,
                        MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }
        }
    }
}
