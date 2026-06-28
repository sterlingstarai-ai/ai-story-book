import '../l10n/app_localizations.dart';
import '../models/book_spec.dart';

/// BookSpec 옵션 enum의 표시 라벨을 현재 로케일로 지역화한다.
/// (enum의 `label`은 한국어 고정 — 백엔드로 보내는 `value`와 달리 화면 표시용이므로 지역화.)

extension TargetAgeL10n on TargetAge {
  String localizedLabel(AppLocalizations l) {
    switch (this) {
      case TargetAge.age3to5:
        return l.libraryAge3to5;
      case TargetAge.age5to7:
        return l.libraryAge5to7;
      case TargetAge.age7to9:
        return l.libraryAge7to9;
      case TargetAge.adult:
        return l.libraryAgeAdult;
    }
  }
}

extension BookStyleL10n on BookStyle {
  String localizedLabel(AppLocalizations l) {
    switch (this) {
      case BookStyle.watercolor:
        return l.libraryStyleWatercolor;
      case BookStyle.cartoon:
        return l.libraryStyleCartoon;
      case BookStyle.threeD:
        return l.libraryStyle3d;
      case BookStyle.pixel:
        return l.libraryStylePixel;
      case BookStyle.oilPainting:
        return l.libraryStyleOilPainting;
      case BookStyle.claymation:
        return l.libraryStyleClaymation;
      case BookStyle.realistic:
        return l.libraryStyleRealistic;
    }
  }
}

extension BookThemeL10n on BookTheme {
  String localizedLabel(AppLocalizations l) {
    switch (this) {
      case BookTheme.lunarNewYear:
        return l.themeLunarNewYear;
      case BookTheme.chuseok:
        return l.themeChuseok;
      case BookTheme.childrensDay:
        return l.themeChildrensDay;
      case BookTheme.christmas:
        return l.themeChristmas;
      case BookTheme.lifestyle:
        return l.themeDailyHabits;
      case BookTheme.emotionalCoaching:
        return l.themeEmotionalCoaching;
      case BookTheme.friendship:
        return l.themeFriendship;
      case BookTheme.family:
        return l.themeFamily;
      case BookTheme.adventure:
        return l.themeAdventure;
      case BookTheme.nature:
        return l.themeNature;
      case BookTheme.science:
        return l.themeScience;
      case BookTheme.timeTravel:
        return l.themeTimeTravel;
      case BookTheme.animal:
        return l.themeAnimal;
      case BookTheme.dinosaur:
        return l.themeDinosaur;
      case BookTheme.occupation:
        return l.themeOccupation;
      case BookTheme.fictionWorld:
        return l.themeFictionWorld;
    }
  }
}
