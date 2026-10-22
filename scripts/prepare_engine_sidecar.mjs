import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const candidates = process.platform === 'win32'
  ? [join(root, '.venv', 'Scripts', 'python.exe')]
  : [join(root, '.venv', 'bin', 'python')];
const python = process.env.NCFD_ENGINE_PYTHON || candidates.find(existsSync);

if (!python || !existsSync(python)) {
  process.stderr.write('找不到專案 Python；請先建立 .venv 並安裝 requirements.txt。\n');
  process.exit(78);
}

const scripts = ['scripts.prepare_local_assets'];
if (!process.argv.includes('--assets-only')) {
  scripts.push('scripts.build_engine_sidecar');
}
for (const script of scripts) {
  const result = spawnSync(python, ['-m', script], {
    cwd: root, stdio: 'inherit',
  });
  if (result.error) {
    process.stderr.write(`${script} 啟動失敗：${result.error.message}\n`);
    process.exit(1);
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
