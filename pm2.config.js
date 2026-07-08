const path = require('path');

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
