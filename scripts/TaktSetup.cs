using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace TaktInstaller
{
    public class SetupForm : Form
    {
        private Label lblTitle;
        private Label lblSub;
        private Label lblPath;
        private TextBox txtPath;
        private Button btnBrowse;
        private CheckBox chkDesktop;
        private CheckBox chkStartMenu;
        private CheckBox chkStartup;
        private CheckBox chkLaunchNow;
        private ProgressBar progressBar;
        private Label lblStatus;
        private Button btnInstall;
        private Button btnCancel;

        private readonly Color BG_DARK = Color.FromArgb(14, 15, 20);
        private readonly Color CARD_BG = Color.FromArgb(21, 22, 30);
        private readonly Color ACCENT = Color.FromArgb(255, 189, 212);
        private readonly Color TEXT_MAIN = Color.FromArgb(244, 244, 245);
        private readonly Color TEXT_MUTED = Color.FromArgb(161, 161, 170);

        public SetupForm()
        {
            InitializeComponent();
        }

        private void InitializeComponent()
        {
            this.Text = "Takt Voice Dictation Setup";
            this.Size = new Size(540, 480);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.BackColor = BG_DARK;
            this.ForeColor = TEXT_MAIN;
            this.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            // Icon if present
            try
            {
                string iconPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "assets", "takt.ico");
                if (File.Exists(iconPath))
                    this.Icon = new Icon(iconPath);
            }
            catch { }

            // Title
            lblTitle = new Label
            {
                Text = "Install Takt",
                Font = new Font("Segoe UI", 16f, FontStyle.Bold),
                ForeColor = TEXT_MAIN,
                Location = new Point(28, 20),
                AutoSize = true
            };
            this.Controls.Add(lblTitle);

            // Subtitle
            lblSub = new Label
            {
                Text = "Super-fast, private local voice dictation for Windows.\nWispr Flow floating pill • DirectML RTX GPU acceleration • Zero bloat",
                Font = new Font("Segoe UI", 9f),
                ForeColor = TEXT_MUTED,
                Location = new Point(30, 56),
                Size = new Size(470, 36)
            };
            this.Controls.Add(lblSub);

            // Install Path Label
            lblPath = new Label
            {
                Text = "Destination Folder:",
                Location = new Point(28, 105),
                AutoSize = true,
                ForeColor = TEXT_MAIN
            };
            this.Controls.Add(lblPath);

            string defaultDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "Takt"
            );

            txtPath = new TextBox
            {
                Text = defaultDir,
                Location = new Point(30, 130),
                Width = 380,
                BackColor = CARD_BG,
                ForeColor = TEXT_MAIN,
                BorderStyle = BorderStyle.FixedSingle
            };
            this.Controls.Add(txtPath);

            btnBrowse = new Button
            {
                Text = "Browse...",
                Location = new Point(418, 128),
                Size = new Size(80, 26),
                BackColor = CARD_BG,
                ForeColor = TEXT_MAIN,
                FlatStyle = FlatStyle.Flat
            };
            btnBrowse.FlatAppearance.BorderColor = Color.FromArgb(46, 50, 66);
            btnBrowse.Click += (s, e) =>
            {
                using (var fbd = new FolderBrowserDialog())
                {
                    fbd.SelectedPath = txtPath.Text;
                    if (fbd.ShowDialog() == DialogResult.OK)
                        txtPath.Text = fbd.SelectedPath;
                }
            };
            this.Controls.Add(btnBrowse);

            // Checkboxes
            chkDesktop = new CheckBox
            {
                Text = "Create Desktop shortcut",
                Checked = true,
                Location = new Point(32, 175),
                AutoSize = true,
                ForeColor = TEXT_MAIN
            };
            this.Controls.Add(chkDesktop);

            chkStartMenu = new CheckBox
            {
                Text = "Create Start Menu shortcut group",
                Checked = true,
                Location = new Point(32, 205),
                AutoSize = true,
                ForeColor = TEXT_MAIN
            };
            this.Controls.Add(chkStartMenu);

            chkStartup = new CheckBox
            {
                Text = "Start Takt automatically on Windows login (Silent Tray)",
                Checked = true,
                Location = new Point(32, 235),
                AutoSize = true,
                ForeColor = TEXT_MAIN
            };
            this.Controls.Add(chkStartup);

            chkLaunchNow = new CheckBox
            {
                Text = "Launch Takt immediately when setup finishes",
                Checked = true,
                Location = new Point(32, 265),
                AutoSize = true,
                ForeColor = TEXT_MAIN
            };
            this.Controls.Add(chkLaunchNow);

            // Progress Bar
            progressBar = new ProgressBar
            {
                Location = new Point(30, 310),
                Size = new Size(468, 10),
                Visible = false
            };
            this.Controls.Add(progressBar);

            // Status label
            lblStatus = new Label
            {
                Text = "Ready to install.",
                Location = new Point(30, 328),
                Size = new Size(468, 20),
                ForeColor = TEXT_MUTED
            };
            this.Controls.Add(lblStatus);

            // Bottom Buttons
            btnInstall = new Button
            {
                Text = "Install Takt",
                Location = new Point(290, 380),
                Size = new Size(110, 34),
                BackColor = ACCENT,
                ForeColor = Color.FromArgb(14, 15, 20),
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold),
                FlatStyle = FlatStyle.Flat,
                Cursor = Cursors.Hand
            };
            btnInstall.FlatAppearance.BorderSize = 0;
            btnInstall.Click += BtnInstall_Click;
            this.Controls.Add(btnInstall);

            btnCancel = new Button
            {
                Text = "Cancel",
                Location = new Point(410, 380),
                Size = new Size(88, 34),
                BackColor = CARD_BG,
                ForeColor = TEXT_MAIN,
                FlatStyle = FlatStyle.Flat
            };
            btnCancel.FlatAppearance.BorderColor = Color.FromArgb(46, 50, 66);
            btnCancel.Click += (s, e) => this.Close();
            this.Controls.Add(btnCancel);
        }

        private void BtnInstall_Click(object sender, EventArgs e)
        {
            if (btnInstall.Text == "Finish")
            {
                this.Close();
                return;
            }

            btnInstall.Enabled = false;
            btnCancel.Enabled = false;
            btnBrowse.Enabled = false;
            txtPath.Enabled = false;
            chkDesktop.Enabled = false;
            chkStartMenu.Enabled = false;
            chkStartup.Enabled = false;
            chkLaunchNow.Enabled = false;

            progressBar.Visible = true;
            progressBar.Style = ProgressBarStyle.Marquee;
            lblStatus.Text = "Installing Takt files...";

            string targetDir = txtPath.Text.Trim();
            bool makeDesktop = chkDesktop.Checked;
            bool makeStartMenu = chkStartMenu.Checked;
            bool enableStartup = chkStartup.Checked;
            bool launch = chkLaunchNow.Checked;

            Thread worker = new Thread(() =>
            {
                try
                {
                    PerformInstall(targetDir, makeDesktop, makeStartMenu, enableStartup, launch);
                    this.Invoke((Action)(() =>
                    {
                        progressBar.Style = ProgressBarStyle.Blocks;
                        progressBar.Value = 100;
                        lblStatus.Text = "Installation complete! Hold Right Alt anywhere to dictate.";
                        lblStatus.ForeColor = Color.FromArgb(52, 211, 153);
                        btnInstall.Text = "Finish";
                        btnInstall.Enabled = true;
                    }));
                }
                catch (Exception ex)
                {
                    this.Invoke((Action)(() =>
                    {
                        progressBar.Visible = false;
                        lblStatus.Text = "Installation error: " + ex.Message;
                        lblStatus.ForeColor = Color.FromArgb(248, 113, 113);
                        btnInstall.Enabled = true;
                        btnCancel.Enabled = true;
                    }));
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }

        private void PerformInstall(string targetDir, bool desktop, bool startMenu, bool startup, bool launch)
        {
            // 1. Kill existing processes
            foreach (var p in Process.GetProcessesByName("Takt"))
            {
                try { p.Kill(); p.WaitForExit(1000); } catch { }
            }
            foreach (var p in Process.GetProcessesByName("TaktApp"))
            {
                try { p.Kill(); p.WaitForExit(1000); } catch { }
            }

            Directory.CreateDirectory(targetDir);

            // 2. Check for payload: Embedded resource, adjacent zip, or adjacent dist\Takt folder
            string currentDir = AppDomain.CurrentDomain.BaseDirectory;
            string adjacentDist = Path.Combine(currentDir, "dist", "Takt");
            if (!Directory.Exists(adjacentDist))
                adjacentDist = Path.Combine(currentDir, "Takt");

            string adjacentZip = Path.Combine(currentDir, "Takt.zip");
            if (!File.Exists(adjacentZip))
                adjacentZip = Path.Combine(currentDir, "dist", "Takt.zip");

            // Look for embedded resource zip
            Assembly asm = Assembly.GetExecutingAssembly();
            string resName = null;
            foreach (var name in asm.GetManifestResourceNames())
            {
                if (name.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
                {
                    resName = name;
                    break;
                }
            }

            if (resName != null)
            {
                using (Stream stream = asm.GetManifestResourceStream(resName))
                using (ZipArchive archive = new ZipArchive(stream))
                {
                    ExtractZipPreservingConfig(archive, targetDir);
                }
            }
            else if (File.Exists(adjacentZip))
            {
                using (ZipArchive archive = ZipFile.OpenRead(adjacentZip))
                {
                    ExtractZipPreservingConfig(archive, targetDir);
                }
            }
            else if (Directory.Exists(adjacentDist))
            {
                CopyDirectory(adjacentDist, targetDir);
            }
            else
            {
                // Fallback: copy repo files
                CopyDirectory(currentDir, targetDir);
            }

            // 3. Compile or copy Uninstall.exe
            string uninstallerExe = Path.Combine(targetDir, "Uninstall.exe");
            string uninstallSource = Path.Combine(currentDir, "scripts", "Uninstall.cs");
            if (File.Exists(uninstallSource))
            {
                CompileCSharp(uninstallSource, uninstallerExe);
            }

            string taktExe = Path.Combine(targetDir, "Takt.exe");
            if (!File.Exists(taktExe))
            {
                string taktApp = Path.Combine(targetDir, "TaktApp.exe");
                if (File.Exists(taktApp))
                {
                    File.Copy(taktApp, taktExe, true);
                }
            }

            string iconPath = Path.Combine(targetDir, "assets", "takt.ico");
            if (!File.Exists(iconPath))
                iconPath = taktExe;

            // 4. Create Desktop Shortcut
            if (desktop && File.Exists(taktExe))
            {
                string deskPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                    "Takt.lnk"
                );
                CreateShortcut(deskPath, taktExe, "", iconPath);
            }

            // 5. Create Start Menu Shortcuts
            if (startMenu && File.Exists(taktExe))
            {
                string startGroup = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
                    "Programs", "Takt"
                );
                Directory.CreateDirectory(startGroup);

                string appLnk = Path.Combine(startGroup, "Takt.lnk");
                CreateShortcut(appLnk, taktExe, "", iconPath);

                string settingsLnk = Path.Combine(startGroup, "Takt Settings.lnk");
                CreateShortcut(settingsLnk, taktExe, "--settings", iconPath);

                if (File.Exists(uninstallerExe))
                {
                    string uninstLnk = Path.Combine(startGroup, "Uninstall Takt.lnk");
                    CreateShortcut(uninstLnk, uninstallerExe, "", uninstallerExe);
                }
            }

            // 6. Register in Windows Registry (Installed Apps)
            try
            {
                using (var key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\Takt"))
                {
                    key.SetValue("DisplayName", "Takt Voice Dictation");
                    key.SetValue("DisplayVersion", "1.0.0");
                    key.SetValue("Publisher", "Desert Ant Labs & Raghav");
                    key.SetValue("InstallLocation", targetDir);
                    key.SetValue("DisplayIcon", taktExe);
                    key.SetValue("UninstallString", string.Format("\"{0}\"", uninstallerExe));
                    key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                    key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                }
            }
            catch { }

            // 7. Register Startup
            if (startup && File.Exists(taktExe))
            {
                try
                {
                    using (var key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run"))
                    {
                        key.SetValue("TaktDictation", string.Format("\"{0}\"", taktExe));
                    }
                }
                catch { }
            }

            // 8. Launch App if requested
            if (launch && File.Exists(taktExe))
            {
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = taktExe,
                    WorkingDirectory = targetDir,
                    UseShellExecute = true
                };
                Process.Start(psi);
            }
        }

        // The user's config\app_config.yaml must never be overwritten by a reinstall/update.
        private static bool IsUserConfig(string path)
        {
            return path.Replace('/', '\\').EndsWith(@"config\app_config.yaml", StringComparison.OrdinalIgnoreCase);
        }

        private static void ExtractZipPreservingConfig(ZipArchive archive, string targetDir)
        {
            foreach (ZipArchiveEntry entry in archive.Entries)
            {
                string destFile = Path.Combine(targetDir, entry.FullName.Replace('/', '\\'));
                if (string.IsNullOrEmpty(entry.Name))
                {
                    Directory.CreateDirectory(destFile);
                    continue;
                }
                if (IsUserConfig(destFile) && File.Exists(destFile)) continue;
                Directory.CreateDirectory(Path.GetDirectoryName(destFile));
                entry.ExtractToFile(destFile, true);
            }
        }

        private static void CopyDirectory(string src, string dst)
        {
            foreach (string dir in Directory.GetDirectories(src, "*", SearchOption.AllDirectories))
            {
                // Skip git and cache
                if (dir.Contains(".git") || dir.Contains("__pycache__")) continue;
                Directory.CreateDirectory(dir.Replace(src, dst));
            }
            foreach (string file in Directory.GetFiles(src, "*.*", SearchOption.AllDirectories))
            {
                if (file.Contains(".git") || file.EndsWith(".pyc")) continue;
                string targetFile = file.Replace(src, dst);
                if (IsUserConfig(targetFile) && File.Exists(targetFile)) continue; // keep user settings
                Directory.CreateDirectory(Path.GetDirectoryName(targetFile));
                File.Copy(file, targetFile, true);
            }
        }

        private static void CreateShortcut(string shortcutPath, string targetPath, string arguments, string iconLocation)
        {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType == null) return;
            dynamic shell = Activator.CreateInstance(shellType);
            dynamic shortcut = shell.CreateShortcut(shortcutPath);
            shortcut.TargetPath = targetPath;
            shortcut.Arguments = arguments;
            shortcut.WorkingDirectory = Path.GetDirectoryName(targetPath);
            if (!string.IsNullOrEmpty(iconLocation) && File.Exists(iconLocation))
                shortcut.IconLocation = iconLocation;
            shortcut.Save();
        }

        private static void CompileCSharp(string sourcePath, string outputPath)
        {
            string csc = @"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe";
            if (!File.Exists(csc)) return;

            ProcessStartInfo psi = new ProcessStartInfo
            {
                FileName = csc,
                Arguments = string.Format("/target:winexe /nologo /out:\"{0}\" \"{1}\"", outputPath, sourcePath),
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using (var p = Process.Start(psi))
            {
                p.WaitForExit(5000);
            }
        }

        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupForm());
        }
    }
}
