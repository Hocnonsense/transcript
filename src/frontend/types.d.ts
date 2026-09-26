import type { Annotation } from './annotation';
import type { ReviewStore } from './reviewstore';
import type { Changes } from './diff';

declare global {
  interface Window {
    hljs: {
      highlight(code: string, options: { language: string }): { value: string };
    };
    Diff?: {
      diffChars: Changes;
      diffWordsWithSpace: Changes;
    };
    markdownit: (preset: string, options: { html: boolean }) => {
      enable(name: string): unknown;
      render(source: string): string;
    };
    snakedoneInitNavigate?: () => void;
    snakedoneReviewStore?: ReviewStore;
  }

  interface HTMLButtonElement {
    sndAnnotation?: Annotation;
    sndHideTimer?: number;
  }
}
