declare module 'd3-cloud' {
  interface Word {
    text?: string;
    size?: number;
    x?: number;
    y?: number;
    rotate?: number;
    font?: string;
    style?: string;
    weight?: string | number;
    padding?: number;
    width?: number;
    height?: number;
    [key: string]: unknown;
  }

  interface Cloud {
    size(size: [number, number]): Cloud;
    words(words: Word[]): Cloud;
    padding(padding: number | ((d: Word) => number)): Cloud;
    rotate(rotate: number | ((d: Word) => number)): Cloud;
    font(font: string | ((d: Word) => string)): Cloud;
    fontStyle(style: string | ((d: Word) => string)): Cloud;
    fontWeight(weight: string | number | ((d: Word) => string | number)): Cloud;
    fontSize(size: number | ((d: Word) => number)): Cloud;
    spiral(spiral: string | ((size: [number, number]) => (t: number) => [number, number])): Cloud;
    timeInterval(interval: number): Cloud;
    random(fn: () => number): Cloud;
    on(event: 'end', callback: (words: Word[]) => void): Cloud;
    on(event: 'word', callback: (word: Word) => void): Cloud;
    start(): Cloud;
    stop(): Cloud;
  }

  function cloud(): Cloud;
  export default cloud;
}
