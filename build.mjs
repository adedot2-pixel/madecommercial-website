// Tiny static site builder: src/pages/*.html + src/partials/layout.html + site.config.json -> dist/
// No dependencies.   node build.mjs            -> dist/ (for deployment)
//                    node build.mjs --offline -> also offline/ (relative links, open index.html straight from disk)
import { readFileSync, writeFileSync, mkdirSync, rmSync, cpSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const site = JSON.parse(readFileSync(join(root, 'site.config.json'), 'utf8'));
const layout = readFileSync(join(root, 'src/partials/layout.html'), 'utf8');
const wantOffline = process.argv.includes('--offline');

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

// Turn root-relative links (/assets/x, /services/) into relative ones so pages work from file://
function relativize(html, depth) {
  const pre = depth ? '../'.repeat(depth) : './';
  return html.replace(/(href|src)="\/(?!\/)([^"]*)"/g, (_, attr, p) => {
    const m = p.match(/^([^?#]*)(.*)$/);
    let path = m[1];
    if (path === '' || path.endsWith('/')) path += 'index.html';
    return `${attr}="${pre}${path}${m[2]}"`;
  });
}

const year = new Date().getFullYear();
const pagesDir = join(root, 'src/pages');
const pages = [];
for (const file of readdirSync(pagesDir).filter((f) => f.endsWith('.html'))) {
  const { meta, body } = parsePage(readFileSync(join(pagesDir, file), 'utf8'));
  const slug = file.replace(/\.html$/, '');
  const out = slug === 'index' ? 'index.html' : slug === '404' ? '404.html' : `${slug}/index.html`;
  const path = slug === 'index' ? '/' : slug === '404' ? '/404.html' : `/${slug}/`;
  const nav = {};
  for (const k of ['services', 'sectors', 'pricing', 'about', 'contact']) nav[k] = meta.nav === k ? 'aria-current="page"' : '';
  const ctx = {
    site, year, nav,
    legalOrName: site.legalName || site.name,
    noindex: meta.noindex === 'true',
    title: esc(meta.title),
    description: esc(meta.description || ''),
    url: site.siteUrl + path,
  };
  const content = render(body, ctx);
  const html = render(layout.replace('{{content}}', () => content), ctx);
  pages.push({ out, path, html, noindex: meta.noindex === 'true' });
}

function emit(dir, relative) {
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  if (existsSync(join(root, 'public'))) cpSync(join(root, 'public'), dir, { recursive: true });
  for (const p of pages) {
    const depth = p.out.split('/').length - 1;
    const html = relative ? relativize(p.html, depth) : p.html;
    mkdirSync(dirname(join(dir, p.out)), { recursive: true });
    writeFileSync(join(dir, p.out), html);
  }
}

const dist = join(root, 'dist');
emit(dist, false);
const urls = pages.filter((p) => !p.noindex).map((p) => site.siteUrl + p.path);
writeFileSync(
  join(dist, 'sitemap.xml'),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
    urls.map((u) => `  <url><loc>${u}</loc></url>`).join('\n') + `\n</urlset>\n`,
);
writeFileSync(join(dist, 'CNAME'), new URL(site.siteUrl).hostname + '\n'); // GitHub Pages custom domain
console.log(`Built ${urls.length} indexable pages into dist/`);

if (wantOffline) {
  emit(join(root, 'offline'), true);
  console.log('Built offline preview into offline/ (open offline/index.html)');
}
