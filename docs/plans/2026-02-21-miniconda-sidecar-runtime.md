# Miniconda Sidecar Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Desktop auto-downloads Miniconda from Tsinghua mirror, silently installs it, creates a conda env, downloads the sidecar code bundle from the backend, pip-installs its requirements, and starts the sidecar — all with a staged progress UI.

**Architecture:** Split the Python runtime concern into two independent pieces: (1) Miniconda, downloaded directly from Tsinghua mirrors and installed once to `<tutorRoot>/miniconda/`, and (2) a platform-agnostic `python_runtime` sidecar code bundle served by the backend containing only sidecar Python source + `requirements.txt`. The conda env's Python is used to start the sidecar; the bundle root provides `app/server/main.py` as the entry point. Both pieces are cached and only re-downloaded when missing or outdated.

**Tech Stack:** Electron (Node.js), React 18, TypeScript, Python 3.12, Miniconda, conda, pip.

---

## Context

| What | Location | Notes |
|------|----------|-------|
| Electron main process | `llm-course-desktop/electron/main.mjs` | ~2000 lines, all IPC handlers here |
| `sidecar:ensureReady` IPC handler | `main.mjs:854` | Currently downloads `python_runtime` bundle with Python binary |
| `startRuntimeInternal` | `main.mjs:1564` | Spawns sidecar process; uses `resolvePythonRuntimeBundle` for python path |
| `downloadToTemp(url, onProgress)` | `main.mjs:368` | Reusable streaming download with progress |
| `installBundleRelease(release, onProgress)` | `main.mjs:458` | Downloads + extracts bundle → updates `active_index.json` |
| `getTutorRoot(settings)` | `main.mjs:52` | Returns `<userData>/TutorApp/` |
| `SidecarDownloadProgress.tsx` | `llm-course-desktop/components/` | Progress UI, phases: checking/downloading/installing/done/error |
| Sidecar deps | `llm-course-sidecar/pyproject.toml` | fastapi, uvicorn, pandas, numpy, openpyxl, etc. |
| Tsinghua Miniconda mirror | `https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/` | Latest py312 versions (Dec 2025) |
| Backend `BundleType` | `llm-course-backend/app/schemas/admin_bundles.py:5` | `Literal["chapter","app_agents","experts","experts_shared","python_runtime"]` |

## Miniconda URLs (Tsinghua, pinned Dec 2025)

```
darwin/arm64:  Miniconda3-py312_25.11.1-1-MacOSX-arm64.sh     (115.8 MiB)
darwin/x64:    Miniconda3-py312_25.7.0-2-MacOSX-x86_64.sh     (112.7 MiB)
win32/x64:     Miniconda3-py312_25.11.1-1-Windows-x86_64.exe  (89.1 MiB)
linux/x64:     Miniconda3-py312_25.11.1-1-Linux-x86_64.sh     (148.2 MiB)
```

Base URL: `https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/`

## New Progress Phases

| Phase | Label (Chinese) | Approx % range |
|-------|----------------|----------------|
| `checking` | 正在检查运行环境... | 0-5 |
| `downloading_conda` | 正在下载 Python 环境 (Miniconda ~100MB)... | 5-35 |
| `installing_conda` | 正在安装 Python 环境... | 35-45 |
| `creating_env` | 正在创建运行环境... | 45-55 |
| `downloading_sidecar` | 正在下载学习引擎... | 55-70 |
| `installing_deps` | 正在安装依赖包... | 70-95 |
| `done` | 准备就绪 | 100 |
| `error` | 出现错误 | — |

## Directory Layout After Setup

```
<tutorRoot>/
  miniconda/              ← Miniconda silent install target
    bin/conda             ← conda binary (macOS/Linux)
    Scripts/conda.exe     ← conda binary (Windows)
    envs/
      sidecar/
        bin/python3       ← Python used to start sidecar (macOS/Linux)
        Scripts/python.exe← Python used to start sidecar (Windows)
        bin/pip           ← pip for installing sidecar requirements
  bundles/
    python_runtime/
      core/
        0.2.0/            ← extracted sidecar code bundle
          runtime.manifest.json
          app/server/main.py   ← entry point (imports from src/sidecar)
          src/sidecar/...      ← full sidecar source
          requirements.txt
```

---

## Task 1: Build script — sidecar code bundle

**Repo:** `llm-course-sidecar`

**Files:**
- Create: `scripts/build_sidecar_code_bundle.py`

This script creates a platform-agnostic `python_runtime` bundle containing only the sidecar Python source + requirements.txt (no Python binary). The bundle structure matches what `resolvePythonRuntimeBundle` in `main.mjs` expects: a `runtime.manifest.json` and an `app/server/main.py` entry point.

**Step 1: Create the build script**

```python
#!/usr/bin/env python3
"""
Build a platform-agnostic sidecar code bundle (python_runtime type, scope_id=core).

Usage:
  python scripts/build_sidecar_code_bundle.py --version 0.2.0 --output /tmp/
"""
import argparse
import hashlib
import io
import json
import tarfile
import sys
from datetime import datetime, timezone
from pathlib import Path


def build_requirements_txt(sidecar_src: Path) -> bytes:
    """Read requirements from pyproject.toml dependencies."""
    pyproject = sidecar_src.parent / "pyproject.toml"
    if not pyproject.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject}")

    import tomllib
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    deps = data.get("project", {}).get("dependencies", [])
    return "\n".join(deps).encode() + b"\n"


def add_bytes(tf: tarfile.TarFile, arcname: str, data: bytes, mode: int = 0o644) -> None:
    ti = tarfile.TarInfo(arcname)
    ti.size = len(data)
    ti.mode = mode
    tf.addfile(ti, io.BytesIO(data))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.2.0")
    parser.add_argument("--scope-id", default="core")
    parser.add_argument("--output", default="/tmp/")
    args = parser.parse_args()

    sidecar_src = Path(__file__).parent.parent / "src" / "sidecar"
    if not sidecar_src.exists():
        print(f"ERROR: sidecar source not found at {sidecar_src}", file=sys.stderr)
        return 1

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"sidecar_code_{args.version}.tar.gz"

    manifest = {
        "format_version": "bundle-v2",
        "bundle_type": "python_runtime",
        "scope_id": args.scope_id,
        "version": args.version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": {
            # No executable_relpath — Python comes from the conda env, not this bundle
        },
        "sidecar": {
            "root_relpath": ".",   # app/server/main.py is at bundle root level
        },
    }

    # Entry point: app/server/main.py adds src/ to sys.path and imports sidecar
    entry_point = (
        "import sys, os\n"
        "_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src')\n"
        "sys.path.insert(0, _src)\n"
        "from sidecar.main import app\n"
    ).encode()

    # Build requirements.txt from pyproject.toml
    try:
        req_bytes = build_requirements_txt(sidecar_src)
    except Exception as e:
        print(f"ERROR building requirements.txt: {e}", file=sys.stderr)
        return 1

    with tarfile.open(out_path, "w:gz") as tf:
        # Manifest
        add_bytes(tf, "runtime.manifest.json", json.dumps(manifest, indent=2).encode())

        # Entry point
        add_bytes(tf, "app/__init__.py", b"")
        add_bytes(tf, "app/server/__init__.py", b"")
        add_bytes(tf, "app/server/main.py", entry_point)

        # requirements.txt
        add_bytes(tf, "requirements.txt", req_bytes)

        # Full sidecar source
        for fpath in sorted(sidecar_src.rglob("*")):
            if fpath.is_dir():
                continue
            if "__pycache__" in str(fpath) or fpath.suffix == ".pyc":
                continue
            rel = fpath.relative_to(sidecar_src.parent.parent / "src")
            arcname = f"src/{rel}"
            tf.add(fpath, arcname=arcname)

    sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
    size = out_path.stat().st_size
    print(f"Wrote:  {out_path}")
    print(f"SHA256: {sha256}")
    print(f"Size:   {size} bytes ({size // 1024 // 1024} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Run the build script to verify it works**

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-sidecar
python scripts/build_sidecar_code_bundle.py --version 0.2.0 --output /tmp/
```

Expected output:
```
Wrote:  /tmp/sidecar_code_0.2.0.tar.gz
SHA256: <64-char hex>
Size:   <N> bytes (<M> MB)
```

**Step 3: Verify bundle structure**

```bash
python3 -c "
import tarfile, json
with tarfile.open('/tmp/sidecar_code_0.2.0.tar.gz', 'r:gz') as tf:
    names = sorted(tf.getnames())
    for n in names[:20]: print(n)
    m = tf.extractfile('runtime.manifest.json')
    print(json.loads(m.read()))
"
```

Expected: see `runtime.manifest.json`, `app/server/main.py`, `requirements.txt`, `src/sidecar/main.py`, etc.

**Step 4: Commit**

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-sidecar
git add scripts/build_sidecar_code_bundle.py
git commit -m "feat: add build_sidecar_code_bundle.py for platform-agnostic sidecar code bundle"
```

---

## Task 2: Upload the sidecar code bundle to the backend

**Repo:** `llm-course-sidecar` (script), `llm-course-backend` (backend receives it)

**Step 1: Upload the bundle**

```bash
curl -X POST \
  -H "X-Admin-Key: 12askd0e8712nkjzs9wfn1" \
  -F "file=@/tmp/sidecar_code_0.2.0.tar.gz" \
  -F "bundle_type=python_runtime" \
  -F "scope_id=core" \
  -F "version=0.2.0" \
  -F "is_mandatory=true" \
  -F 'manifest_json={"platform":"all"}' \
  "http://47.93.151.131:10723/v1/admin/bundles/upload" | python3 -m json.tool
```

Expected: 201 response with artifact_url.

**Step 2: Verify check-app returns the new bundle**

```bash
# Get a token
TOKEN=$(curl -s -X POST http://47.93.151.131:10723/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"student@example.com","password":"StrongPass123","device_id":"verify-001"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

# Check-app with no python_runtime installed
curl -s -X POST http://47.93.151.131:10723/v1/updates/check-app \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"installed":{"python_runtime":""},"platform_scope":"py312-darwin-arm64"}' \
  | python3 -m json.tool
```

Expected: response includes `python_runtime` bundle with `scope_id: "core"`, `version: "0.2.0"`.

**Step 3: No commit needed** (this is a manual data upload step, not a code change).

---

## Task 3: Add Miniconda helpers to electron/main.mjs

**Repo:** `llm-course-desktop`

**Files:**
- Modify: `electron/main.mjs` — add constants and helper functions after the existing `getPlatformScopeId` function (around line 838)

**Step 1: Add the Miniconda URL map and path helpers**

Find the line:
```js
const getPlatformScopeId = () => {
  const platform = process.platform === 'win32' ? 'win' : process.platform === 'darwin' ? 'darwin' : 'linux';
  const arch = process.arch === 'arm64' ? 'arm64' : 'x64';
  return `py312-${platform}-${arch}`;
};
```

Immediately after that function, add:

```js
// ---------------------------------------------------------------------------
// Miniconda runtime management
// ---------------------------------------------------------------------------

const MINICONDA_BASE_URL = 'https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/';

const MINICONDA_FILENAME = (() => {
  const { platform, arch } = process;
  if (platform === 'darwin' && arch === 'arm64') return 'Miniconda3-py312_25.11.1-1-MacOSX-arm64.sh';
  if (platform === 'darwin') return 'Miniconda3-py312_25.7.0-2-MacOSX-x86_64.sh';
  if (platform === 'win32') return 'Miniconda3-py312_25.11.1-1-Windows-x86_64.exe';
  return 'Miniconda3-py312_25.11.1-1-Linux-x86_64.sh'; // linux x64
})();

const getCondaRoot = (tutorRoot) => path.join(tutorRoot, 'miniconda');

const getCondaBin = (condaRoot) => process.platform === 'win32'
  ? path.join(condaRoot, 'Scripts', 'conda.exe')
  : path.join(condaRoot, 'bin', 'conda');

const getCondaEnvPython = (condaRoot) => process.platform === 'win32'
  ? path.join(condaRoot, 'envs', 'sidecar', 'Scripts', 'python.exe')
  : path.join(condaRoot, 'envs', 'sidecar', 'bin', 'python3');

const getCondaEnvPip = (condaRoot) => process.platform === 'win32'
  ? path.join(condaRoot, 'envs', 'sidecar', 'Scripts', 'pip.exe')
  : path.join(condaRoot, 'envs', 'sidecar', 'bin', 'pip');

const runSubprocess = (executable, args, options = {}) => new Promise((resolve, reject) => {
  const child = spawn(executable, args, {
    stdio: ['ignore', 'pipe', 'pipe'],
    ...options,
  });
  let stderr = '';
  child.stderr?.on('data', (d) => { stderr += d.toString(); });
  child.on('close', (code) => {
    if (code === 0) resolve({ code, stderr });
    else reject(new Error(`${path.basename(executable)} exited ${code}: ${stderr.slice(-500)}`));
  });
  child.on('error', reject);
});
```

**Step 2: Verify syntax compiles** (no test framework for main.mjs, just check with node):

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-desktop
node --input-type=module < electron/main.mjs 2>&1 | head -5
# Expected: either silence or the usual Electron "cannot use outside electron" error, NOT a SyntaxError
```

Actually just check syntax with:
```bash
node --check electron/main.mjs 2>&1 | head -10
```
Expected: no output (no syntax errors).

**Step 3: Commit**

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-desktop
git add electron/main.mjs
git commit -m "feat: add Miniconda URL map and conda path helpers to main.mjs"
```

---

## Task 4: Add ensureCondaInstalled() and ensureCondaEnv() to main.mjs

**Files:**
- Modify: `electron/main.mjs` — add two functions after the helpers from Task 3

**Step 1: Add `ensureCondaInstalled(condaRoot, tutorRoot, sendProgress)`**

Add immediately after the `runSubprocess` helper:

```js
const ensureCondaInstalled = async (condaRoot, sendProgress) => {
  const condaBin = getCondaBin(condaRoot);
  if (await pathExists(condaBin)) {
    return; // already installed
  }

  // Download installer
  const installerUrl = MINICONDA_BASE_URL + MINICONDA_FILENAME;
  const ext = process.platform === 'win32' ? '.exe' : '.sh';
  const installerPath = path.join(os.tmpdir(), `miniconda-installer-${Date.now()}${ext}`);

  sendProgress('downloading_conda', { percent: 5, status: '正在下载 Python 环境...' });

  const response = await fetch(installerUrl);
  if (!response.ok) {
    throw new Error(`Miniconda download failed (${response.status}): ${installerUrl}`);
  }

  const totalBytes = Number(response.headers.get('content-length') || 0);
  const chunks = [];
  let bytesDownloaded = 0;

  if (response.body) {
    const reader = response.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(Buffer.from(value));
      bytesDownloaded += value.length;
      const rawPercent = totalBytes > 0 ? (bytesDownloaded / totalBytes) : 0;
      // Map download progress to 5-33% range
      const displayPercent = Math.round(5 + rawPercent * 28);
      sendProgress('downloading_conda', {
        percent: displayPercent,
        bytesDownloaded,
        totalBytes,
        status: '正在下载 Python 环境...',
      });
    }
  } else {
    const data = Buffer.from(await response.arrayBuffer());
    chunks.push(data);
  }

  await fs.writeFile(installerPath, Buffer.concat(chunks));
  sendProgress('installing_conda', { percent: 35, status: '正在安装 Python 环境...' });

  // Silent install
  await ensureDir(condaRoot);
  if (process.platform === 'win32') {
    await runSubprocess(installerPath, ['/S', `/D=${condaRoot}`]);
  } else {
    await fs.chmod(installerPath, 0o755);
    await runSubprocess('bash', [installerPath, '-b', '-p', condaRoot]);
  }

  // Write .condarc to use Tsinghua channels
  const condarc = [
    'default_channels:',
    '  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main',
    '  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r',
    'show_channel_urls: true',
  ].join('\n') + '\n';
  await fs.writeFile(path.join(condaRoot, '.condarc'), condarc, 'utf8');

  // Clean up installer
  await fs.unlink(installerPath).catch(() => {});

  sendProgress('installing_conda', { percent: 44, status: '正在安装 Python 环境...' });
};

const ensureCondaEnv = async (condaRoot, sendProgress) => {
  const envPython = getCondaEnvPython(condaRoot);
  if (await pathExists(envPython)) {
    return; // env already exists
  }

  sendProgress('creating_env', { percent: 45, status: '正在创建运行环境...' });

  const condaBin = getCondaBin(condaRoot);
  await runSubprocess(condaBin, [
    'create', '-n', 'sidecar', 'python=3.12', '--yes', '--quiet',
    '--override-channels',
    '--channel', 'https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main',
  ]);

  sendProgress('creating_env', { percent: 54, status: '正在创建运行环境...' });
};
```

**Step 2: Check syntax**

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-desktop
node --check electron/main.mjs 2>&1 | head -10
```
Expected: no output.

**Step 3: Commit**

```bash
git add electron/main.mjs
git commit -m "feat: add ensureCondaInstalled() and ensureCondaEnv() to main.mjs"
```

---

## Task 5: Add ensureSidecarCode() to main.mjs

**Files:**
- Modify: `electron/main.mjs` — add after `ensureCondaEnv`

**Step 1: Add `ensureSidecarCode(condaRoot, tutorRoot, sendProgress)`**

```js
const ensureSidecarCode = async (condaRoot, sendProgress) => {
  // 1. Check current installed version from index
  const indexData = await loadIndex();
  const settings = await loadSettings();
  const installedVersions = {
    app_agents: indexData?.app_agents?.core?.version || '',
    experts_shared: indexData?.experts_shared?.shared?.version || '',
    python_runtime: (() => {
      const entries = Object.values(indexData?.python_runtime || {});
      return entries.length > 0 ? String(entries[0]?.version || '') : '';
    })(),
  };

  sendProgress('downloading_sidecar', { percent: 55, status: '正在检查学习引擎版本...' });

  // 2. Call check-app to find out if an update is available
  const checkResult = await requestBackend({
    method: 'POST',
    path: '/v1/updates/check-app',
    body: {
      desktop_version: app.getVersion() || '0.1.0',
      sidecar_version: installedVersions.python_runtime || '0.0.0',
      installed: installedVersions,
      platform_scope: getPlatformScopeId(),
    },
    withAuth: true,
  });

  if (!checkResult.ok) {
    // If already installed, tolerate network failure
    if (installedVersions.python_runtime) {
      return;
    }
    throw new Error(`Sidecar code check failed (${checkResult.status})`);
  }

  const allReleases = [
    ...(checkResult.data?.required || []),
    ...(checkResult.data?.optional || []),
  ];
  const sidecarRelease = allReleases.find((r) => r.bundle_type === 'python_runtime');

  if (!sidecarRelease) {
    if (installedVersions.python_runtime) {
      return; // already up to date
    }
    throw new Error('No sidecar code bundle available from server');
  }

  // 3. Download and extract the bundle
  sendProgress('downloading_sidecar', { percent: 56, status: '正在下载学习引擎...' });

  let downloadComplete = false;
  await installBundleRelease(sidecarRelease, (progress) => {
    if (!downloadComplete) {
      // Map download to 56-68%
      const displayPercent = Math.round(56 + (progress.percent / 100) * 12);
      sendProgress('downloading_sidecar', {
        percent: displayPercent,
        bytesDownloaded: progress.bytesDownloaded,
        totalBytes: progress.totalBytes,
        status: '正在下载学习引擎...',
      });
      if (progress.percent >= 100) downloadComplete = true;
    }
  });

  // 4. Find the installed bundle root in the updated index
  const updatedIndex = await loadIndex();
  const prEntries = Object.entries(updatedIndex?.python_runtime || {}).filter(([, e]) => e?.path);
  if (prEntries.length === 0) {
    throw new Error('Sidecar bundle installed but not found in index');
  }
  const bundleRoot = String(prEntries[0][1].path);

  // 5. pip install requirements into the conda env
  const requirementsTxt = path.join(bundleRoot, 'requirements.txt');
  if (await pathExists(requirementsTxt)) {
    sendProgress('installing_deps', { percent: 70, status: '正在安装依赖包...' });
    const pipBin = getCondaEnvPip(condaRoot);
    await runSubprocess(pipBin, [
      'install', '-r', requirementsTxt,
      '--index-url', 'https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/',
      '--trusted-host', 'mirrors.tuna.tsinghua.edu.cn',
      '--quiet',
    ]);
    sendProgress('installing_deps', { percent: 95, status: '正在安装依赖包...' });
  }
};
```

**Step 2: Check syntax**

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-desktop
node --check electron/main.mjs 2>&1 | head -10
```

**Step 3: Commit**

```bash
git add electron/main.mjs
git commit -m "feat: add ensureSidecarCode() — download sidecar bundle and pip install deps into conda env"
```

---

## Task 6: Rewrite sidecar:ensureReady handler + update startRuntimeInternal

**Files:**
- Modify: `electron/main.mjs:854` — the `sidecar:ensureReady` IPC handler
- Modify: `electron/main.mjs:1564` — `startRuntimeInternal`

**Step 1: Replace the body of `sidecar:ensureReady`**

Find:
```js
ipcMain.handle('sidecar:ensureReady', async () => {
  const indexData = await loadIndex();
  // ... (existing ~110 lines until the closing });
```

Replace the entire handler body with:

```js
ipcMain.handle('sidecar:ensureReady', async () => {
  const settings = await loadSettings();
  const tutorRoot = getTutorRoot(settings);
  const condaRoot = getCondaRoot(tutorRoot);

  const sendProgress = (phase, progress) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('sidecar:download-progress', { phase, ...progress });
    }
  };

  try {
    sendProgress('checking', { percent: 0, status: '正在检查运行环境...' });

    // Stage 1: Miniconda installation (skipped if already present)
    await ensureCondaInstalled(condaRoot, sendProgress);

    // Stage 2: Conda sidecar env (skipped if already present)
    await ensureCondaEnv(condaRoot, sendProgress);

    // Stage 3: Sidecar code bundle + pip install (skipped if up to date)
    await ensureSidecarCode(condaRoot, sendProgress);

    sendProgress('done', { percent: 100, status: '准备就绪' });
    return { ready: true };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    sendProgress('error', { percent: 0, status: message });
    return { ready: false, error: message };
  }
});
```

**Step 2: Add `resolveCondaEnvPython` helper and update `startRuntimeInternal`**

Find the function `startRuntimeInternal` (around line 1564). Near the top of that function, find:

```js
  const bundledRuntime = await resolvePythonRuntimeBundle(indexData);
  const runtimeCwd = bundledRuntime?.runtimeCwd || (await resolveRuntimeProjectRoot());
  const pythonPath = runtimeConfig?.pythonPath || process.env.TUTOR_PYTHON || bundledRuntime?.pythonPath || 'python';
```

Replace those 3 lines with:

```js
  const bundledRuntime = await resolvePythonRuntimeBundle(indexData);
  const runtimeCwd = bundledRuntime?.runtimeCwd || (await resolveRuntimeProjectRoot());

  // Prefer the conda env Python over the bundle's embedded Python (which no longer exists)
  const condaRoot = getCondaRoot(tutorRoot);
  const condaEnvPython = getCondaEnvPython(condaRoot);
  const condaPythonExists = await pathExists(condaEnvPython);
  const pythonPath = runtimeConfig?.pythonPath
    || process.env.TUTOR_PYTHON
    || (condaPythonExists ? condaEnvPython : '')
    || bundledRuntime?.pythonPath
    || 'python';
```

**Step 3: Check syntax**

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-desktop
node --check electron/main.mjs 2>&1 | head -10
```
Expected: no output.

**Step 4: Commit**

```bash
git add electron/main.mjs
git commit -m "feat: rewrite sidecar:ensureReady with Miniconda flow; use conda env Python in startRuntimeInternal"
```

---

## Task 7: Extend SidecarDownloadProgress.tsx with new phases

**Repo:** `llm-course-desktop`

**Files:**
- Modify: `components/SidecarDownloadProgress.tsx`

**Step 1: Read the current file**

Read `llm-course-desktop/components/SidecarDownloadProgress.tsx`.

**Step 2: Update the `SidecarDownloadState` type and `phaseLabel` map**

Find the current type:
```ts
export interface SidecarDownloadState {
  phase: 'checking' | 'downloading' | 'installing' | 'done' | 'error';
  percent: number;
  bytesDownloaded?: number;
  totalBytes?: number;
  status: string;
}
```

Replace with:
```ts
export interface SidecarDownloadState {
  phase:
    | 'checking'
    | 'downloading_conda'
    | 'installing_conda'
    | 'creating_env'
    | 'downloading_sidecar'
    | 'installing_deps'
    | 'done'
    | 'error';
  percent: number;
  bytesDownloaded?: number;
  totalBytes?: number;
  status: string;
}
```

Find the current `phaseLabel`:
```ts
const phaseLabel: Record<string, string> = {
  checking: '正在检查学习引擎...',
  downloading: '正在下载学习引擎...',
  installing: '正在安装...',
  done: '准备就绪',
  error: '出现错误',
};
```

Replace with:
```ts
const phaseLabel: Record<string, string> = {
  checking:           '正在检查运行环境...',
  downloading_conda:  '正在下载 Python 环境 (Miniconda)...',
  installing_conda:   '正在安装 Python 环境...',
  creating_env:       '正在创建运行环境...',
  downloading_sidecar:'正在下载学习引擎...',
  installing_deps:    '正在安装依赖包...',
  done:               '准备就绪',
  error:              '出现错误',
};
```

Also update `isActive`:
```ts
const isActive = !isError && !isDone;
```
This line is already correct — all non-done/error phases show the progress bar.

**Step 3: Run TypeScript check**

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-desktop
npm run build:desktop 2>&1 | grep -E "error TS|warning" | head -20
```
Or just check types:
```bash
npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.

**Step 4: Commit**

```bash
git add components/SidecarDownloadProgress.tsx
git commit -m "feat: extend SidecarDownloadProgress with Miniconda setup phase labels"
```

---

## Task 8: Manual end-to-end verification

**This is a manual test — no automated test for Electron main process flows.**

**Step 1: Clear any existing conda install to simulate first launch**

```bash
# Remove conda if present (check first!)
ls ~/Library/Application\ Support/Knoweia/TutorApp/miniconda/ 2>/dev/null \
  && echo "exists — remove to test fresh install" \
  || echo "not present — good, will test fresh install"

# To fully reset:
# rm -rf ~/Library/Application\ Support/Knoweia/TutorApp/miniconda/
# Also remove any existing python_runtime bundle entry from active_index.json
```

**Step 2: Start the desktop in dev mode**

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-desktop
npm run dev:desktop
```

**Step 3: Log in with the test student account**

- Email: `student@example.com` / Password: `StrongPass123`

**Step 4: Observe the progress overlay**

Watch the `SidecarDownloadProgress` overlay go through stages:
1. "正在检查运行环境..." (instant)
2. "正在下载 Python 环境 (Miniconda)..." with MB/total and percent (1-3 min)
3. "正在安装 Python 环境..." (30s)
4. "正在创建运行环境..." (1-2 min)
5. "正在下载学习引擎..." (seconds — small bundle)
6. "正在安装依赖包..." (pandas/numpy install, 2-5 min)
7. "准备就绪" → overlay dismisses

**Step 5: Verify sidecar is running**

```bash
curl http://127.0.0.1:8000/health
# Expected: {"status": "healthy"}
```

**Step 6: Verify conda Python was used**

In Electron DevTools (Ctrl+Shift+I or Cmd+Opt+I), check console for:
```
runtime_source: "python_runtime:core"
python_source: "python_runtime:core"
```

**Step 7: Subsequent launch — must be fast (< 10s)**

Close and reopen the app. The overlay should flash briefly ("正在检查运行环境...") and disappear. No downloads should occur. Verify in DevTools console that `alreadyInstalled: true` is logged or that the sidecar starts within ~5 seconds.

**Step 8: Commit (nothing to commit — this is a manual test step)**

---

## Task 9: Push all desktop and sidecar changes

**Step 1: Verify both repos are clean**

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-sidecar && git status
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-desktop && git status
```

**Step 2: Push**

```bash
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-sidecar && git push origin main
cd /Users/houyuxin/08Coding/llm-learning-platform/llm-course-desktop && git push origin main
```

---

## Execution Order

```
Task 1: Build script                  [sidecar repo, code]
Task 2: Upload sidecar code bundle    [manual backend upload]
Task 3: Miniconda helpers in main.mjs [desktop code]
Task 4: ensureCondaInstalled/Env      [desktop code]
Task 5: ensureSidecarCode             [desktop code]
Task 6: Rewrite ensureReady + startRuntimeInternal [desktop code]
Task 7: Extend SidecarDownloadProgress.tsx [desktop code]
Task 8: Manual E2E verification       [manual]
Task 9: Push                          [git]
```

Tasks 3–7 are all `electron/main.mjs` or `SidecarDownloadProgress.tsx`. They build on each other sequentially. Each is committed separately for easy bisect if needed.

## Known Constraints

- **`runSubprocess` is synchronous-blocking for the IPC handler.** Conda install and pip install are long-running (minutes). The Electron `ipcMain.handle` coroutine will be blocked during these operations, which is acceptable because the UI thread stays responsive (IPC handler runs in main process, UI in renderer). The progress events via `mainWindow.webContents.send` still fire during the subprocess, because they're emitted from the progress callbacks, not from a blocked await.

  **WRONG assumption:** `runSubprocess` resolves after the subprocess exits. During that time, only the Node.js event loop in the main process is waiting. The BrowserWindow renderer process remains fully responsive. Progress events are delivered normally.

- **pip install blocks without streaming progress.** The `installing_deps` phase shows a fixed 70% → 95% jump. If you want line-by-line pip progress, you'd need to spawn pip differently and parse its output — YAGNI for v1.

- **No resume on crash.** If the user kills the app during Miniconda install, the partial install in `<tutorRoot>/miniconda/` may be corrupt. On next launch, `getCondaBin(condaRoot)` check will re-detect missing binary and redo the install. The partial directory will be overwritten by the bash installer (`-b` flag overwrites without prompt).

- **Windows path with spaces.** `getTutorRoot` may return a path with spaces (e.g. `C:\Users\John Smith\...`). The Miniconda Windows installer `/D=` flag doesn't handle quoted paths. Ensure `tutorRoot` doesn't have spaces by warning or sanitizing. For v1 this is an edge case — document it, don't fix it.
