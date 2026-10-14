using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace TaktSettingsLauncher
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            try
            {
                string appDir = AppDomain.CurrentDomain.BaseDirectory;
                string taktExe = Path.Combine(appDir, "Takt.exe");

                if (File.Exists(taktExe))
                {
                    ProcessStartInfo psi = new ProcessStartInfo
                    {
                        FileName = taktExe,
                        Arguments = "--settings",
                        WorkingDirectory = appDir,
                        UseShellExecute = true
                    };
                    Process.Start(psi);
                    return;
                }

                // Fallback to pythonw if running in source tree
                string settingsScript = Path.Combine(appDir, "src", "ui", "settings_gui.py");
                if (File.Exists(settingsScript))
                {
                    string pythonw = FindPythonW();
                    ProcessStartInfo psi = new ProcessStartInfo
                    {
                        FileName = pythonw,
                        Arguments = "\"" + settingsScript + "\"",
                        WorkingDirectory = appDir,
                        CreateNoWindow = true,
                        WindowStyle = ProcessWindowStyle.Hidden,
                        UseShellExecute = false
                    };
                    string currentPyPath = Environment.GetEnvironmentVariable("PYTHONPATH") ?? "";
                    psi.EnvironmentVariables["PYTHONPATH"] = appDir + ";" + currentPyPath;
                    Process.Start(psi);
                    return;
                }

                MessageBox.Show("Could not find Takt.exe in: " + appDir, "Takt Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            catch (Exception ex)
            {
                MessageBox.Show("Failed to launch Takt Settings:\n" + ex.Message, "Takt Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        static string FindPythonW()
        {
            string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string py310 = Path.Combine(localApp, @"Programs\Python\Python310\pythonw.exe");
            if (File.Exists(py310)) return py310;
            return "pythonw.exe";
        }
    }
}
