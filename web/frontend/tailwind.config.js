/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./*.html', './scripts/**/*.js'],
  theme: {
    extend: {
      colors: {
        vdos: {
          50:  '#E6F1FB',
          100: '#B5D4F4',
          400: '#378ADD',
          500: '#185FA5',
          700: '#0C447C',
          900: '#042C53',
        },
        gain: {
          50:  '#EAF3DE',
          700: '#27500A',
          900: '#173404',
        },
        loss: {
          50:  '#FCEBEB',
          700: '#791F1F',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SF Mono', 'Menlo', 'Consolas', 'monospace'],
        serif: ['ui-serif', 'Georgia', 'Times New Roman', 'serif'],
      },
      fontWeight: {
        normal: '400',
        medium: '500',
      },
      borderRadius: {
        chip: '8px',
        card: '12px',
      },
    },
  },
  corePlugins: {
    fontWeight: true,
  },
  plugins: [],
};
