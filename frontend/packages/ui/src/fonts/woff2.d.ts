// Vite turns an imported font file into its URL (bundled, served by the app; never a CDN).
declare module '*.woff2' {
  const url: string;
  export default url;
}
