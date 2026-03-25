# brew-ui — LabBREW React Frontend

Browser UI for the LabBREW fermentation management platform.

For full documentation — features, architecture, and setup instructions — see the [Frontend Documentation](../../../../docs/frontend/README.md).

## Quick Start

```bash
npm install
npm run dev      # development server at http://localhost:5173
```

The backend must be running before the UI is useful:

```bash
# from the project root
python run_supervisor.py           # node supervisor
python run_FrontEndsupervisor.py   # BrewSupervisor gateway (port 8782)
```

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Vite development server with HMR |
| `npm run build` | Production build (output in `dist/`) |
| `npm run preview` | Locally preview the production build |
| `npm run lint` | Run ESLint |
