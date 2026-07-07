module.exports = {
  apps: [
    {
      name: 'sol-radar',
      // Use the venv's Python binary directly — PM2 can't misparse a binary as JS
      script: './venv/bin/python',
      args: '-m uvicorn app.main:app --host 0.0.0.0 --port 8000',
      interpreter: 'none',
      autorestart: true,
      watch: false, // Don't use --reload in production
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: '.',
        // Ensure the venv's bin is on PATH for any subprocess calls
        PATH: `${__dirname}/venv/bin:${process.env.PATH}`,
        VIRTUAL_ENV: `${__dirname}/venv`,
      },
    },
  ],
}
