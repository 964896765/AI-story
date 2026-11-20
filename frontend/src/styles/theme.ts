import { buttonDark, cardDark, createTheme, modalDark, tagDark, type GlobalThemeOverrides } from 'naive-ui'

export const workbenchTheme = createTheme('dark', [buttonDark, cardDark, modalDark, tagDark])

export const componentTheme: GlobalThemeOverrides = {
  common: {
    primaryColor: '#83ded1', primaryColorHover: '#a0ece0', primaryColorPressed: '#53bfb1', primaryColorSuppl: '#83ded1',
    bodyColor: '#11161d', cardColor: '#172029', modalColor: '#172029', borderColor: '#324150',
    textColorBase: '#f0f5fa', textColor1: '#f0f5fa', textColor2: '#d3dfe9', textColor3: '#a0b1c2',
    successColor: '#8fd0b3', warningColor: '#e6bd81', errorColor: '#f3a1ab',
    borderRadius: '8px', borderRadiusSmall: '6px',
    fontFamily: '"Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif',
  },
}
