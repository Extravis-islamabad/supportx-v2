// Metro for an app outside the frontend pnpm workspace that uses its shared packages
// (docs/architecture/mobile.md, "Repo integration").
const path = require('node:path');

const { getDefaultConfig } = require('expo/metro-config');

const projectRoot = __dirname;
const sharedPackages = path.resolve(projectRoot, '../frontend/packages') + path.sep;

const config = getDefaultConfig(projectRoot);

// The linked @supportx/* sources live outside the project; Metro must watch them.
config.watchFolders = [sharedPackages];

/**
 * Package imports made by the shared packages resolve as if made from this app: their own
 * node_modules hold React 18 and other web-test copies, and two Reacts in one bundle fail with
 * "Invalid hook call". So the app's copy of React, TanStack Query and i18next is the only one.
 * Relative imports inside the shared packages resolve normally.
 */
const isBare = (name) => !name.startsWith('.') && !path.isAbsolute(name);
config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (context.originModulePath.startsWith(sharedPackages) && isBare(moduleName)) {
    const fromApp = { ...context, originModulePath: path.join(projectRoot, 'package.json') };
    return context.resolveRequest(fromApp, moduleName, platform);
  }
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = config;
