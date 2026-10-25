// Execute the installed server's actual LayoutManager and Layout enum modules.
// Usage: node tests/web_layout.cjs /path/to/main.jellyfin.bundle.js
// No browser, account, localStorage database or server mutation is involved.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const modules = [...source.matchAll(/(?:^|[,\{])(\d+):function\(e,t,n\)\{/g)];
function moduleContaining(marker) {
    const position = source.indexOf(marker);
    assert(position >= 0, `Missing upstream marker: ${marker}`);
    const index = modules.findLastIndex(m => m.index < position);
    assert(index >= 0 && modules[index + 1], 'Unsupported bundle format');
    const start = modules[index].index + modules[index][0].length;
    const end = modules[index + 1].index;
    const body = source.slice(start, end);
    assert(body.endsWith('}'), 'Unsupported module boundary');
    return new Function('e', 't', 'n', body.slice(0, -1));
}
const enumModule = moduleContaining('e.DesktopLegacy="desktop-legacy"');
const layoutModule = moduleContaining('key:"getSavedLayout"');
function run(native, saved, expectedModern, expectedTv) {
    const classes = new Set();
    global.document = { documentElement: { classList: {
        add: name => classes.add(name), remove: name => classes.delete(name)
    } } };
    const enums = {};
    const requireStub = () => ({});
    requireStub.d = (exports, getters) => {
        for (const [key, get] of Object.entries(getters)) Object.defineProperty(exports, key, { get });
    };
    enumModule({}, enums, requireStub);
    // Resolve imports by their use, so unrelated side-effect polyfills stay inert.
    const text = layoutModule.toString();
    const importId = name => {
        const alias = text.match(new RegExp('\\b([a-z])\\.' + name.replaceAll('.', '\\.')))[1];
        return Number(text.match(new RegExp(alias + '=n\\((\\d+)\\)'))[1]);
    };
    const deps = new Map([
        [importId('S'), enums],
        [importId('g'), { g: { getDefaultLayout: () => native } }],
        [importId('A.mobile'), { A: { mobile: false, tv: false } }],
        [importId('A.get'), { A: { get: () => saved, set: () => {} } }],
        [importId('A.trigger'), { A: { trigger: () => {} } }]
    ]);
    const req = id => deps.get(id) || {};
    req.d = requireStub.d;
    const exports = {};
    layoutModule({}, exports, req);
    assert.equal(exports.A.modern, expectedModern);
    assert.equal(exports.A.tv, expectedTv);
    assert.equal(exports.A.desktop, !expectedTv);
    console.log(`PASS native=${native} saved=${saved}: modern=${expectedModern}, tv=${expectedTv}`);
}
run('desktop', undefined, true, false);
run('tv', undefined, false, true);
run('desktop', 'desktop-legacy', false, false);
run('desktop', 'tv', false, true); // explicit web preference takes precedence
run('tv', 'desktop', true, false);
