import os
import winreg
from PIL import Image
import ctypes

def setup_icon():
    # 1. Convert PNG to ICO
    png_path = r"C:\Users\makse\.gemini\antigravity-ide\brain\8c53e53e-7ca7-4a87-8ed7-a9e79bf918b6\cortex_file_icon_1786612093630.png"
    ico_path = r"C:\Users\makse\OneDrive\Desktop\НОВЫЙ ЯЗЫК\cortex_icon.ico"
    
    img = Image.open(png_path)
    img.save(ico_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print(f"Created icon at {ico_path}")

    # 2. Register in Windows Registry
    # Create .ctx extension
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.ctx")
        winreg.SetValue(key, "", winreg.REG_SZ, "Cortex.File")
        winreg.CloseKey(key)
        
        # Create Cortex.File class and set DefaultIcon
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\Cortex.File\DefaultIcon")
        winreg.SetValue(key, "", winreg.REG_SZ, f"{ico_path}")
        winreg.CloseKey(key)
        
        print("Registry updated successfully!")
        
        # 3. Notify Windows Explorer to refresh icons
        # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        print("Explorer icons refreshed!")
    except Exception as e:
        print(f"Failed to update registry: {e}")

if __name__ == "__main__":
    setup_icon()
