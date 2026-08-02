// @rhwp/core 의 브라우저 자산(rhwp.js, rhwp_bg.wasm)을 static/ 으로 복사한다.
// render.html 이 same-origin 으로 import 하므로 서버가 static/ 에서 서빙한다.
const fs = require("fs");
const path = require("path");

const outDir = path.join(__dirname, "..", "static");
fs.mkdirSync(outDir, { recursive: true });

for (const f of ["rhwp.js", "rhwp_bg.wasm"]) {
  try {
    const src = require.resolve(`@rhwp/core/${f}`);
    fs.copyFileSync(src, path.join(outDir, f));
    console.log(`copied ${f}`);
  } catch (e) {
    console.error(`copy-rhwp: ${f} 복사 실패 — @rhwp/core 설치 확인: ${e.message}`);
    process.exit(1);
  }
}
