// The brand images are imported as URLs, which Vite (apps, Vitest) resolves. The apps get this
// from `vite/client`; this package has no Vite dependency of its own.
declare module '*.png' {
  const url: string;
  export default url;
}
