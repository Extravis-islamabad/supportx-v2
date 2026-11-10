// The app's verified sign-in return links (ADR-044 item 3), added to app.json at build time.
//
// The sign-in comes back to https://<SupportX host>/mobile/auth (the chart's mobile.returnPath).
// iOS hands that link only to this app through a Universal Link (associated domains) and Android
// through a verified App Link (autoVerify), once the host serves apple-app-site-association and
// assetlinks.json naming this build (the chart's mobile.ios.appIds and mobile.android values).
// Only /mobile/auth* opens the app: every other address on the host stays in the browser.
//
// Each build lists the SupportX hosts it serves, comma-separated, in SUPPORTX_APP_LINK_HOSTS
// (e.g. "support.example.com"). On-prem and air-gapped customers build with their own host,
// bundle ID and signing key. No custom-scheme sign-in return: any app could claim it.
const RETURN_PATH = '/mobile/auth';

const hosts = (process.env.SUPPORTX_APP_LINK_HOSTS ?? '')
  .split(',')
  .map((host) => host.trim())
  .filter((host) => host !== '');

module.exports = ({ config }) => ({
  ...config,
  ios: {
    ...config.ios,
    associatedDomains: hosts.map((host) => `applinks:${host}`),
  },
  android: {
    ...config.android,
    intentFilters:
      hosts.length === 0
        ? []
        : [
            {
              action: 'VIEW',
              autoVerify: true,
              data: hosts.map((host) => ({ scheme: 'https', host, pathPrefix: RETURN_PATH })),
              category: ['BROWSABLE', 'DEFAULT'],
            },
          ],
  },
});
