/** Leaving the console for Microsoft's or Google's sign-in page (tests spy on `go`). */
export const browser = {
  go(url: string): void {
    window.location.assign(url);
  },
};
