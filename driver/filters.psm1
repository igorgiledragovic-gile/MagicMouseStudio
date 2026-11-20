# Helpers: read/modify LowerFilters of device instances via SetupAPI (works as admin; Enum keys are SYSTEM-owned).
$src = @'
using System; using System.Runtime.InteropServices; using System.Text; using System.Collections.Generic;
public static class DevFilters {
  [StructLayout(LayoutKind.Sequential)] public struct SP_DEVINFO_DATA { public int cbSize; public Guid ClassGuid; public int DevInst; public IntPtr Reserved; }
  [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr SetupDiGetClassDevsW(IntPtr g, string enumerator, IntPtr hwnd, int flags);
  [DllImport("setupapi.dll", SetLastError=true)] static extern bool SetupDiEnumDeviceInfo(IntPtr set, int i, ref SP_DEVINFO_DATA d);
  [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiGetDeviceInstanceIdW(IntPtr set, ref SP_DEVINFO_DATA d, StringBuilder id, int n, out int req);
  [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiGetDeviceRegistryPropertyW(IntPtr set, ref SP_DEVINFO_DATA d, int prop, out int type, byte[] buf, int n, out int req);
  [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiSetDeviceRegistryPropertyW(IntPtr set, ref SP_DEVINFO_DATA d, int prop, byte[] buf, int n);
  [DllImport("setupapi.dll")] static extern bool SetupDiDestroyDeviceInfoList(IntPtr set);
  const int SPDRP_LOWERFILTERS = 0x12, DIGCF_ALLCLASSES = 0x4;

  static string[] ReadMulti(IntPtr set, ref SP_DEVINFO_DATA d) {
    int type, req; byte[] buf = new byte[2048];
    if (!SetupDiGetDeviceRegistryPropertyW(set, ref d, SPDRP_LOWERFILTERS, out type, buf, buf.Length, out req)) return new string[0];
    return Encoding.Unicode.GetString(buf, 0, req).Split(new char[]{'\0'}, StringSplitOptions.RemoveEmptyEntries);
  }
  // mode: "get" | "add" | "remove". Returns "instanceId => filters" lines.
  public static List<string> Apply(string enumerator, string idPattern, string filter, string mode) {
    var res = new List<string>(); IntPtr set = SetupDiGetClassDevsW(IntPtr.Zero, enumerator, IntPtr.Zero, DIGCF_ALLCLASSES);
    try {
      for (int i = 0; ; i++) {
        var d = new SP_DEVINFO_DATA(); d.cbSize = Marshal.SizeOf(d);
        if (!SetupDiEnumDeviceInfo(set, i, ref d)) break;
        var sb = new StringBuilder(512); int req; SetupDiGetDeviceInstanceIdW(set, ref d, sb, sb.Capacity, out req);
        string id = sb.ToString(); if (id.ToUpperInvariant().IndexOf(idPattern.ToUpperInvariant()) < 0) continue;
        var list = new List<string>(ReadMulti(set, ref d));
        bool changed = false;
        if (mode == "add" && !list.Exists(x => string.Equals(x, filter, StringComparison.OrdinalIgnoreCase))) { list.Add(filter); changed = true; }
        // first entry in LowerFilters = lowest in the stack (closest to the bus PDO)
        if (mode == "prepend") {
          int at = list.FindIndex(x => string.Equals(x, filter, StringComparison.OrdinalIgnoreCase));
          if (at != 0) { if (at > 0) list.RemoveAt(at); list.Insert(0, filter); changed = true; }
        }
        if (mode == "remove") changed = list.RemoveAll(x => string.Equals(x, filter, StringComparison.OrdinalIgnoreCase)) > 0;
        if (changed) {
          byte[] b = Encoding.Unicode.GetBytes(string.Join("\0", list.ToArray()) + "\0\0");
          bool ok = list.Count == 0 ? SetupDiSetDeviceRegistryPropertyW(set, ref d, SPDRP_LOWERFILTERS, null, 0)
                                    : SetupDiSetDeviceRegistryPropertyW(set, ref d, SPDRP_LOWERFILTERS, b, b.Length);
          if (!ok) { res.Add(id + " => ERROR " + Marshal.GetLastWin32Error()); continue; }
        }
        res.Add(id + " => {" + string.Join(",", list.ToArray()) + "}" + (changed ? " (changed)" : ""));
      }
    } finally { SetupDiDestroyDeviceInfoList(set); }
    return res;
  }
}
'@
if (-not ('DevFilters' -as [type])) { Add-Type -TypeDefinition $src }

function Set-MmsLowerFilter([string]$Enumerator, [string]$IdPattern, [string]$Filter, [ValidateSet('get','add','prepend','remove')][string]$Mode) {
  [DevFilters]::Apply($Enumerator, $IdPattern, $Filter, $Mode)
}
Export-ModuleMember -Function Set-MmsLowerFilter
