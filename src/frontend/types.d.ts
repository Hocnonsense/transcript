interface Window {
  hljs: {
    highlight(code: string, options: { language: string }): { value: string };
  };
  markdownit: (
    preset: string,
    options: { html: boolean },
  ) => {
    enable(name: string): unknown;
    render(source: string): string;
  };
  snakedoneInitNavigate?: () => void;
}

interface HTMLButtonElement {
  sndAnnotation?: unknown;
}
