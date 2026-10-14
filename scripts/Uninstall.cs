using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
using Microsoft.Win32;

namespace TaktInstaller
{
    static class Uninstaller
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            var result = MessageBox.Show(
                "Are you sure you want to completely uninstall Takt Voice Dictation from your system?",
                "Uninstall Takt",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question
            );

            if (result != DialogResult.Yes)
                return;

            string appDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');

            // 1. Kill running Takt processes
            try
            {
                foreach (var p in Process.GetProcessesByName("Takt"))
                {
                    try { p.Kill(); } catch { }
                }
                foreach (var p in Process.GetProcessesByName("TaktApp"))
                {
                    try { p.Kill(); } catch { }
                }
            }
            catch { }

            // 2. Remove Windows Startup Registry Key
            try
            {
                using (var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", true))
                {
                    if (key != null)
                        key.DeleteValue("TaktDictation", false);
                }
            }
            catch { }

            // 3. Remove Windows Uninstall Registry Key
            try
            {
                Registry.CurrentUser.DeleteSubKeyTree(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\Takt", false);
            }
            catch { }

            // 4. Remove Desktop Shortcut
            try
            {
                string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                string lnk = Path.Combine(desktop, "Takt.lnk");
                if (File.Exists(lnk)) File.Delete(lnk);
            }
            catch { }

            // 5. Remove Start Menu Group
            try
            {
                string startMenu = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
                    "Programs", "Takt"
                );
                if (Directory.Exists(startMenu))
                    Directory.Delete(startMenu, true);
            }
            catch { }

            // 6. Delete directory self-destruct via cmd
            MessageBox.Show(
                "Takt Voice Dictation has been successfully uninstalled.",
                "Takt Uninstalled",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information
            );

            ProcessStartInfo psi = new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = string.Format("/c ping 127.0.0.1 -n 2 > nul & rmdir /s /q \"{0}\"", appDir),
                WindowStyle = ProcessWindowStyle.Hidden,
                CreateNoWindow = true,
                UseShellExecute = true
            };
            Process.Start(psi);
        }
    }
}
