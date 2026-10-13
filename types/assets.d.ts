declare module "*.svg" {
  const src: string;
  export default src;
}

interface ImportMeta {
  readonly env: { readonly DEV: boolean };
}

declare module "*.html?raw" {
  const content: string;
  export default content;
}

declare module "*.module.css" {
  const classes: { readonly [key: string]: string };
  export default classes;
}
