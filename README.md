# MADE Commercial website

Static site for www.madecommercial.co.uk. No dependencies: `node build.mjs` turns `src/` + `public/` into `dist/`.

- Edit copy in `src/pages/*.html`; shared header/footer in `src/partials/layout.html`.
- Contact and company details live in `site.config.json`. Empty fields (phone, company number, registered office, LinkedIn) are hidden until filled in.
- Preview locally: `npm run dev` then open http://localhost:4173
- Deploys to GitHub Pages on every push to `main` (`.github/workflows/pages.yml`).

## Before going live
1. Set up a real mailbox for `email` in `site.config.json` (the domain has no MX records yet).
2. Optional: create a Formspree form and put its URL in `formEndpoint`. Until then the contact form opens the visitor's email app.
3. Fill in `legalName`, `companyNumber` and `registeredOffice` (UK law requires these on a company website).
4. Check the About and Privacy copy.

## DNS (GoDaddy)
- Change only the `www` record: CNAME `www` -> `adedot2-pixel.github.io`.
- Do NOT touch the `pricing` CNAME (Render).
- Make the bare domain redirect to www using GoDaddy forwarding.
