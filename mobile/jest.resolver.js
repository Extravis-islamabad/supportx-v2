// Jest's twin of the resolveRequest rule in metro.config.js: package imports made by the shared
// packages (../frontend/packages) resolve from this app, so tests run on the app's single React,
// TanStack Query, i18next and Babel runtime rather than the web workspace's copies.
const path = require('node:path');

const sharedPackages = path.resolve(__dirname, '../frontend/packages') + path.sep;
const isBare = (request) => !request.startsWith('.') && !path.isAbsolute(request);

module.exports = (request, options) => {
  if (isBare(request) && path.resolve(options.basedir).startsWith(sharedPackages)) {
    return options.defaultResolver(request, { ...options, basedir: __dirname });
  }
  return options.defaultResolver(request, options);
};
