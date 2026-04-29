import type { SearchResult } from './types';

export const SAMPLE_RESULTS: SearchResult[] = [
  {
    id: '1',
    kind: 'pdf',
    kindLabel: 'PDF',
    date: 'Oct 12, 2023',
    title: 'Sustainable Packaging Options Guide 2024',
    snippet:
      'Comprehensive overview of eco-friendly materials including PCR (Post-Consumer Recycled) plastics, glass alternatives, and biodegradable resins available for Q1.',
  },
  {
    id: '2',
    kind: 'video',
    kindLabel: 'Video Transcript',
    date: 'Sep 28, 2023',
    title: 'Webinar: Sourcing PCR Bottles',
    snippet:
      '...when discussing sustainable bottle options, the transition to 100% PCR requires careful consideration of structural integrity and clarity constraints...',
  },
  {
    id: '3',
    kind: 'article',
    kindLabel: 'Article',
    date: 'Aug 05, 2023',
    title: 'Vendor Comparison: Glass vs. PET',
    snippet:
      'Cost analysis and lead time comparison for standard 8oz and 16oz containers across our top three domestic suppliers.',
  },
];
