import { writable } from 'svelte/store';

export const authed = writable<boolean | null>(null); // null = loading
