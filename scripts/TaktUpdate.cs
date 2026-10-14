using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Threading;
using System.Windows.Forms;

namespace TaktUpdater
{
    public class UpdateForm : Form
    {
        private Label lblTitle;
        private Label lblStatus;
        private ProgressBar progressBar;
        private Button btnAction;
        private string updateZipPath;

        private readonly Color BG_DARK = Color.FromArgb(14, 15, 20);
        private readonly Color CARD_BG = Color.FromArgb(21, 22, 30);
        private readonly Color ACCENT = Color.FromArgb(255, 189, 212);
        private readonly Color TEXT_MAIN = Color.FromArgb(244, 244, 245);
        private readonly Color TEXT_MUTED = Color.FromArgb(161, 161, 170);

        public UpdateForm(string zipPath = null)
        {
            this.updateZipPath = zipPath;
            InitializeComponent();
        }

        private void InitializeComponent()
        {
            this.Text = "Takt Software Updater";
            this.Size = new Size(460, 260);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.BackColor = BG_DARK;
            this.ForeColor = TEXT_MAIN;
            this.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            try
            {
                string iconPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "assets", "takt.ico");
                if (File.Exists(iconPath)) this.Icon = new Icon(iconPath);
            }
            catch { }

            lblTitle = new Label
            {
                Text = "Updating Takt Voice Dictation",
                Font = new Font("Segoe UI", 13f, FontStyle.Bold),
                ForeColor = TEXT_MAIN,
                Location = new Point(24, 20),
                AutoSize = true
            };
            this.Controls.Add(lblTitle);

            lblStatus = new Label
            {
                Text = "Preparing update...",
                Location = new Point(26, 60),
                Size = new Size(400, 40),
                ForeColor = TEXT_MUTED
            };
            this.Controls.Add(lblStatus);

            progressBar = new ProgressBar
            {
                Location = new Point(26, 110),
                Size = new Size(392, 12),
                Style = ProgressBarStyle.Marquee
            };
            this.Controls.Add(progressBar);

            btnAction = new Button
            {
                Text = "Start Update",
                Location = new Point(298, 160),
                Size = new Size(120, 34),
                BackColor = ACCENT,
                ForeColor = Color.FromArgb(14, 15, 20),
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold),
                FlatStyle = FlatStyle.Flat,
                Cursor = Cursors.Hand
            };
            btnAction.FlatAppearance.BorderSize = 0;
            btnAction.Click += BtnAction_Click;
            this.Controls.Add(btnAction);

            this.Load += (s, e) =>
            {
                if (!string.IsNullOrEmpty(updateZipPath) && File.Exists(updateZipPath))
                {
                    StartUpdateProcess(updateZipPath);
                }
                else
                {
                    lblStatus.Text = "Select an update package (.zip) or click below to proceed.";
                    btnAction.Text = "Select Zip...";
                }
            };
        }

        private void BtnAction_Click(object sender, EventArgs e)
        {
            if (btnAction.Text == "Finish" || btnAction.Text == "Close")
            {
                this.Close();
                return;
            }

            using (var ofd = new OpenFileDialog())
            {
                ofd.Filter = "Takt Update Zip (*.zip)|*.zip|All files (*.*)|*.*";
                ofd.Title = "Select Takt Update Package";
                if (ofd.ShowDialog() == DialogResult.OK)
                {
                    this.updateZipPath = ofd.FileName;
                    StartUpdateProcess(this.updateZipPath);
                }
            }
        }

        private void StartUpdateProcess(string zipFile)
        {
            btnAction.Enabled = false;
            progressBar.Style = ProgressBarStyle.Marquee;
            lblStatus.Text = "Closing running Takt processes...";
            lblStatus.ForeColor = TEXT_MAIN;

            Thread worker = new Thread(() =>
            {
                try
                {
                    // 1. Terminate running Takt processes
                    foreach (var p in Process.GetProcessesByName("Takt"))
                    {
                        try { p.Kill(); p.WaitForExit(2000); } catch { }
                    }
                    foreach (var p in Process.GetProcessesByName("TaktApp"))
                    {
                        try { p.Kill(); p.WaitForExit(2000); } catch { }
                    }

                    // 2. Identify target directory
                    string targetDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
                    string localAppDir = Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                        "Programs", "Takt"
                    );
                    if (Directory.Exists(localAppDir) && File.Exists(Path.Combine(localAppDir, "Takt.exe")))
                    {
                        targetDir = localAppDir;
                    }

                    this.Invoke((Action)(() => lblStatus.Text = "Applying update files to: " + targetDir));

                    // 3. Extract zip, preserving user's config/app_config.yaml
                    using (ZipArchive archive = ZipFile.OpenRead(zipFile))
                    {
                        foreach (ZipArchiveEntry entry in archive.Entries)
                        {
                            if (string.IsNullOrEmpty(entry.Name))
                            {
                                // Directory
                                continue;
                            }

                            string entryRel = entry.FullName.Replace('/', '\\');
                            // Skip overwriting user's existing personal app_config.yaml
                            if (entryRel.EndsWith(@"config\app_config.yaml", StringComparison.OrdinalIgnoreCase))
                            {
                                string existingConfig = Path.Combine(targetDir, entryRel);
                                if (File.Exists(existingConfig))
                                {
                                    continue; // Preserve user custom settings
                                }
                            }

                            string destFile = Path.Combine(targetDir, entryRel);
                            Directory.CreateDirectory(Path.GetDirectoryName(destFile));
                            entry.ExtractToFile(destFile, true);
                        }
                    }

                    // 4. Restart Takt
                    string taktExe = Path.Combine(targetDir, "Takt.exe");
                    if (File.Exists(taktExe))
                    {
                        Process.Start(new ProcessStartInfo
                        {
                            FileName = taktExe,
                            WorkingDirectory = targetDir,
                            UseShellExecute = true
                        });
                    }

                    this.Invoke((Action)(() =>
                    {
                        progressBar.Style = ProgressBarStyle.Blocks;
                        progressBar.Value = 100;
                        lblStatus.Text = "Takt has been updated and restarted successfully!";
                        lblStatus.ForeColor = Color.FromArgb(52, 211, 153);
                        btnAction.Text = "Finish";
                        btnAction.Enabled = true;
                    }));
                }
                catch (Exception ex)
                {
                    this.Invoke((Action)(() =>
                    {
                        progressBar.Visible = false;
                        lblStatus.Text = "Update error: " + ex.Message;
                        lblStatus.ForeColor = Color.FromArgb(248, 113, 113);
                        btnAction.Text = "Close";
                        btnAction.Enabled = true;
                    }));
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }

        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string zipArg = args.Length > 0 ? args[0] : null;
            Application.Run(new UpdateForm(zipArg));
        }
    }
}
