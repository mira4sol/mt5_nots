const path = require('path');
const fs = require('fs');

function loadDotEnv(filePath) {
  const env = {};
  if (!fs.existsSync(filePath)) {
    return env;
  }
  for (const line of fs.readFileSync(filePath, 'utf8').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) {
      continue;
    }
    const idx = trimmed.indexOf('=');
    if (idx === -1) {
      continue;
    }
    const key = trimmed.slice(0, idx).trim();
    let value = trimmed.slice(idx + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    env[key] = value;
  }
  return env;
}

const dotenv = loadDotEnv(path.join(__dirname, '.env'));

module.exports = {
  apps: [
    {
      name: 'mt5-trigger',
      cwd: __dirname,
      // Use the venv Python directly — PM2 treats script as the executable
      script: path.join(__dirname, '.venv', 'bin', 'python'),
      args: '-m mt5_trigger',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 5000,
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: path.join(__dirname, 'src'),
        VIRTUAL_ENV: path.join(__dirname, '.venv'),
        COMMAND_API_TOKEN: dotenv.COMMAND_API_TOKEN || process.env.COMMAND_API_TOKEN || '',
        // openclaw CLI for WhatsApp sends (adjust if installed elsewhere)
        PATH: `${path.join(__dirname, '.venv', 'bin')}:${process.env.PATH}`,
      },
      // Logs (optional — pm2 default is ~/.pm2/logs/)
      error_file: path.join(__dirname, 'data', 'pm2-error.log'),
      out_file: path.join(__dirname, 'data', 'pm2-out.log'),
      merge_logs: true,
      time: true,
    },
  ],
};
