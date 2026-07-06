/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // GROWX palette
        navy: '#0B3A4A',
        blue: '#2D82A9',
        cyan: '#37B6C7',
        green: '#64B26A',
        gold: '#F2B541',
        gray: {
          DEFAULT: '#8D9AA0',
          light: '#BFEFF0',
        },
        // Sober surface scale derived from navy, for a dense dark UI.
        ink: {
          900: '#07222C',
          800: '#0B3A4A',
          700: '#0F4557',
          600: '#155062',
          500: '#1D5E72',
        },
      },
      fontFamily: {
        display: ['Poppins', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        body: ['Montserrat', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
    },
  },
  plugins: [],
};
