const fs = require('node:fs');
const path = require('node:path');

const root = process.cwd();
const candidates = ['tests/e2e', 'e2e', 'tests'].map((name) => path.resolve(root, name));
const testDir = candidates.find((dir) => fs.lstatSync(dir, { throwIfNoEntry: false })?.isDirectory());

module.exports = {
  testDir: testDir ?? path.join(root, 'tests'),
  outputDir: path.join(root, 'test-results'),
};
