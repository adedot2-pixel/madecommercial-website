// Tiny static site builder: src/pages/*.html + src/partials/layout.html + site.config.json -> dist/
// No dependencies. Run: node build.mjs
import { readFileSync, writeFileSync, mkdirSync, rmSync, cpSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const dist = join(root, 'dist');
const site = JSON.parse(readFileSync(join(root, 'site.config.json'), 'utf8'));
const layout = readFileSync(join(root, 'src/partials/layout.html'), 'utf8');

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
const lookup = (ctx, path) => path.split('.').reduce((o, k) => (o == null ? o : o[k]), ctx);

function render(tpl, ctx) {
  // {{#if key}}...{{/if}} (no nesting), then {{key}} / {{a.b}}
  tpl = tpl.replace(/\{\{#if ([\w.]+)\}\}([\s\S]*?)\{\{\/if\}\}/g, (_, k, body) => (lookup(ctx, k) ? body : ''));
  return tpl.replace(/\{\{([\w.]+)\}\}/g, (m, k) => {
    const v = lookup(ctx, k);
    return v == null ? m : String(v);
  });
}

function parsePage(src) {
  const m = src.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!m) throw new Error('page is missing front matter');
  const meta = {};
  for (const line of m[1].split('\n')) {
    const i = line.indexOf(':');
    if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return { meta, body: m[2] };
}

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });
if (existsSync(join(root, 'public'))) cpSync(join(root, 'public'), dist, { recursive: true });

const year = new Date().getFullYear();
const urls = [];
const pagesDir = join(root, 'src/pages');

for (const file of readdirSync(pagesDir).filter((f) => f.endsWith('.html'))) {
  const { meta, body } = parsePage(readFileSync(join(pagesDir, file), 'utf8'));
  const slug = file.replace(/\.html$/, '');
  const out = slug === 'index' ? 'index.html' : slug === '404' ? '404.html' : `${slug}/index.html`;
  const path = slug === 'index' ? '/' : slug === '404' ? '/404.html' : `/${slug}/`;

  const nav = {};
  for (const k of ['services', 'pricing', 'about', 'contact']) nav[k] = meta.nav === k ? 'aria-current="page"' : '';

  const ctx = {
    site,
    year,
    nav,
    legalOrName: site.legalName || site.name,
    noindex: meta.noindex === 'true',
    title: esc(meta.title),
    description: esc(meta.description || ''),
    url: site.siteUrl + path,
  };
  const content = render(body, ctx);
  const html = render(layout.replace('{{content}}', () => content), ctx);

  mkdirSync(dirname(join(dist, out)), { recursive: true });
  writeFileSync(join(dist, out), html);
  if (meta.noindex !== 'true') urls.push(site.siteUrl + path);
}

writeFileSync(
  join(dist, 'sitemap.xml'),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
    urls.map((u) => `  <url><loc>${u}</loc></url>`).join('\n') +
    `\n</urlset>\n`,
);

// GitHub Pages custom domain
writeFileSync(join(dist, 'CNAME'), new URL(site.siteUrl).hostname + '\n');

console.log(`Built ${urls.length} indexable pages into dist/`);
