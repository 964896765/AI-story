import { buttonDark, cardDark, createTheme, modalDark, tagDark, type GlobalThemeOverrides } from 'naive-ui'

export const workbenchTheme = createTheme('dark', [buttonDark, cardDark, modalDark, tagDark])

export const componentTheme: GlobalThemeOverrides = {
  common: {
    primaryColor: '#afa1f0', primaryColorHover: '#c1b6fa', primaryColorPressed: '#9987e8', primaryColorSuppl: '#afa1f0',
    bodyColor: '#16171b', cardColor: '#202127', modalColor: '#202127', borderColor: '#34353f',
    textColorBase: '#f4f2fa', textColor1: '#f4f2fa', textColor2: '#d9d6e0', textColor3: '#a7a5b2',
    successColor: '#8fd0b3', warningColor: '#e6bd81', errorColor: '#f3a1ab',
    borderRadius: '8px', borderRadiusSmall: '6px',
    fontFamily: '"Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif',
  },
}
