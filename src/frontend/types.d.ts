import type { Annotation } from './review/annotation';
import type { ReviewStore } from './review/reviewstore';
import type { Changes } from './review/text/diff';

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
    transcriptInitNavigate?: () => void;
    transcriptReviewStore?: ReviewStore;
  }

  interface HTMLButtonElement {
    tmdAnnotation?: Annotation;
    tmdHideTimer?: number;
  }
}
