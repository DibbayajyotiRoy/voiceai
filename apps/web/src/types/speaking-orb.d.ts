import type { DetailedHTMLProps, HTMLAttributes } from "react";

// The vendored <speaking-orb> custom element (public/vendor/speaking-orb.js).
declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "speaking-orb": DetailedHTMLProps<
        HTMLAttributes<HTMLElement> & { state?: string; particles?: number | string },
        HTMLElement
      >;
    }
  }
}
