import fs from "node:fs";
import path from "node:path";
import { transform } from "@babel/standalone";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const staticRoot = path.resolve(here, "../backend/app/static");
const components = ["Icon.js", "Toast.js", "StatCard.js", "SectionHeader.js", "Forms.js", "App.js"];
const built = components.map((name) => {
  const source = fs.readFileSync(path.join(staticRoot, "components", name), "utf8");
  const compiled = transform(source, { presets: ["react"], sourceMaps: false, compact: true }).code;
  return `(function(){${compiled}${name === "App.js" ? "window.App = App;" : ""}})();`;
}).join("\n");
const assets = path.join(staticRoot, "assets");
fs.mkdirSync(assets, { recursive: true });
const fetchShim = `const _fetch = window.fetch.bind(window); window.fetch = (input, init = {}) => { const headers = new Headers(init.headers || {}); headers.delete('Authorization'); const csrf = document.cookie.split('; ').find(v => v.startsWith('csrf_token=')); if (!['GET','HEAD','OPTIONS'].includes((init.method || 'GET').toUpperCase()) && csrf) headers.set('X-CSRF-Token', decodeURIComponent(csrf.split('=').slice(1).join('='))); return _fetch(input, {...init, headers, credentials: 'include'}); };`;
fs.writeFileSync(path.join(assets, "dashboard.js"), `${fetchShim}\n${built}\nconst root = ReactDOM.createRoot(document.getElementById('root')); root.render(React.createElement(App));\n`);
fs.copyFileSync(path.join(here, "node_modules/react/umd/react.production.min.js"), path.join(assets, "react.min.js"));
fs.copyFileSync(path.join(here, "node_modules/react-dom/umd/react-dom.production.min.js"), path.join(assets, "react-dom.min.js"));
fs.copyFileSync(path.join(here, "node_modules/lucide/dist/umd/lucide.min.js"), path.join(assets, "lucide.min.js"));
fs.writeFileSync(path.join(assets, "tailwind.input.css"), "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n");
execFileSync(process.execPath, [path.join(here, "node_modules/tailwindcss/lib/cli.js"), "-c", path.join(here, "tailwind.config.js"), "-i", path.join(assets, "tailwind.input.css"), "-o", path.join(assets, "tailwind.css"), "--minify"], { stdio: "inherit" });
console.log("Built pinned local dashboard assets.");
