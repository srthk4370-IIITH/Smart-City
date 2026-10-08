import subprocess, sys
print("python", sys.version.split()[0])
print(subprocess.run("free -g; nproc; df -h / /kaggle/working /tmp 2>/dev/null; ls /dev | grep -i -E 'accel|vfio' | head", shell=True, capture_output=True, text=True).stdout)
