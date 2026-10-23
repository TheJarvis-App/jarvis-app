// The repo folder and the Python that runs the computer side, on any system: a file path (not a URL path, which on
// Windows reads "/C:/Users/%D7..."), and the venv's Python where there is one (bin/ or, on Windows, Scripts/).
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const venv = path.join(ROOT, "venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
export const PY = process.env.JARVIS_PY || (existsSync(venv) ? venv : process.platform === "win32" ? "python" : "python3");
