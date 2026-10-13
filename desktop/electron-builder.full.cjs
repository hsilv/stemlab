// The "full" installer: the same app plus its Python runtime and packages, so the first start
// downloads nothing (models still download the first time each one is used).
//
// Build it on the platform it is for (`npm run dist:full`). The Linux .deb is a few GB. Windows is
// a zip (extract and run StemLab.exe): an NSIS installer cannot hold more than 2 GB.
const base = require("./package.json").build;

module.exports = {
  ...base,
  artifactName: "${productName}-${version}-full.${ext}",
  extraResources: [...base.extraResources, { from: "resources/runtime", to: "runtime" }],
  win: { target: ["zip"] },
  linux: { ...base.linux, target: ["deb"] },
  deb: { ...base.deb, compression: "gz" },
};
