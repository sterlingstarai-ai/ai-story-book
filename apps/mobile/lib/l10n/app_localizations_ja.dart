// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Japanese (`ja`).
class AppLocalizationsJa extends AppLocalizations {
  AppLocalizationsJa([String locale = 'ja']) : super(locale);

  @override
  String get appTitle => 'AIえほん';

  @override
  String get readingGrowthTitle => '読書の成長';

  @override
  String get readingGrowthEntryTitle => '読書の成長を見る';

  @override
  String get readingGrowthEntrySubtitle => 'お子さまの読書力が育つ様子';

  @override
  String get estimatedReadingLevel => 'お子さまの推定読書レベル';

  @override
  String get booksReadLabel => '読んだ本';

  @override
  String get currentStreakLabel => '連続読書';

  @override
  String get vocabLearnedLabel => '学んだ語彙';

  @override
  String get quizAccuracyLabel => 'クイズ正答率';

  @override
  String get retry => '再試行';

  @override
  String get onboardingSkip => 'スキップ';

  @override
  String get onboardingNext => '次へ';

  @override
  String get onboardingStart => 'はじめる';

  @override
  String get onboardingSlide1Title => 'AIオーダーメイド絵本';

  @override
  String get onboardingSlide1Subtitle => 'お子さまに合ったお話をAIが作ります。';

  @override
  String get onboardingSlide2Title => '写真からキャラクター作成';

  @override
  String get onboardingSlide2Subtitle => 'お子さまの写真を絵本の主人公にできます。';

  @override
  String get onboardingSlide3Title => '毎日の読書習慣';

  @override
  String get onboardingSlide3Subtitle => 'ストリークで毎日の読書習慣を育てます。';

  @override
  String get onboardingSlide4Title => '無料ではじめる';

  @override
  String get onboardingSlide4Subtitle => '初回3クレジットですぐに絵本を作れます。';

  @override
  String onboardingPageIndicator(int current, int total) {
    return '$totalページ中$currentページ目';
  }

  @override
  String get homeTitle => 'AI絵本';

  @override
  String get homeSettingsTooltip => '設定';

  @override
  String get homeHeaderSubtitle => 'お子さま向けのオリジナル絵本を作りましょう';

  @override
  String get homeSectionTodayReading => '今日の読書';

  @override
  String get homeSectionForParents => '保護者の方へ';

  @override
  String get homeRecentBooksTitle => '最近作った絵本';

  @override
  String get homeViewAll => 'すべて見る';

  @override
  String get homeEmptyTitle => 'まだ作った絵本がありません';

  @override
  String get homeEmptySubtitle => '最初の絵本を作ってみましょう！';

  @override
  String get homeLibraryErrorTitle => '絵本を読み込めませんでした';

  @override
  String get homeCreateCardTitle => '新しい絵本を作る';

  @override
  String get homeCreateCardSubtitle => 'お子さまが主人公の\nオリジナル絵本を作ります';

  @override
  String get homeQuickStartTitle => 'キャラクターからすぐ作る';

  @override
  String get homePhotoCharacterTitle => 'わが子で絵本を作る';

  @override
  String get homePhotoCharacterSubtitle => '写真そっくりの主人公に — 写真は安全に処理されます';

  @override
  String homeStreakDaysLabel(Object days) {
    return '$days日連続の読書';
  }

  @override
  String get homeReadTodayBadge => '今日読みました';

  @override
  String get homeNotReadTodayBadge => '今日は未完了';

  @override
  String homeStreakSummary(Object total, Object longest) {
    return '合計$total日読みました · 最高$longest日';
  }

  @override
  String get homeRecent7Days => '直近7日間';

  @override
  String homeTodayStoryLabel(Object theme) {
    return '今日の絵本 · $theme';
  }

  @override
  String get homeContinueReading => '続きを読む';

  @override
  String get homeMakeTodayStory => '今日の絵本を作る';

  @override
  String get homeStreakLoading => 'ストリーク情報を読み込み中...';

  @override
  String get homeStreakErrorTitle => 'ストリークカードのエラー';

  @override
  String get homeStreakLoadError => 'ストリーク情報を読み込めませんでした。';

  @override
  String get homeGrowthEntryTitle => '読書の成長を見る';

  @override
  String homeGrowthSubtitleStats(Object vocab, Object accuracy) {
    return '学習語彙$vocab語 · 正確度$accuracy%';
  }

  @override
  String get homeWeekdayMon => '月';

  @override
  String get homeWeekdayTue => '火';

  @override
  String get homeWeekdayWed => '水';

  @override
  String get homeWeekdayThu => '木';

  @override
  String get homeWeekdayFri => '金';

  @override
  String get homeWeekdaySat => '土';

  @override
  String get homeWeekdaySun => '日';

  @override
  String get homeWeekdayUnknown => '-';

  @override
  String get createTitle => '新しい絵本を作る';

  @override
  String get createCloseTooltip => '閉じる';

  @override
  String get createTopicLabel => 'どんなお話を作りましょうか?';

  @override
  String get createTopicHint => '例:ウサギが空を飛ぶお話';

  @override
  String get createTopicRequired => 'お話のテーマを入力してください';

  @override
  String get createTopicTooShort => 'もう少し詳しく入力してください';

  @override
  String get createChildNameLabel => 'お子さまの名前(任意)';

  @override
  String get createChildNameHint => '例:ミンジ';

  @override
  String get createAgeLabel => 'お子さまの年齢層';

  @override
  String get createAgeHelp3to5 => 'やさしい言葉、1〜2文の短い文、繰り返しと擬音語';

  @override
  String get createAgeHelp5to7 => '身近な言葉、2〜3文、感情と簡単な会話';

  @override
  String get createAgeHelp7to9 => '豊かな言葉、2〜4文、原因と結果';

  @override
  String get createAgeHelpAdult => '長さ制限なし、密度の高い物語';

  @override
  String get createLanguageLabel => '物語の言語';

  @override
  String get createTemplateSectionLabel => 'おすすめから始める';

  @override
  String get createTemplateAnimalLabel => 'どうぶつの友だち';

  @override
  String get createTemplateAnimalTopic => '勇敢な小さな動物が森で新しい友だちを作るお話';

  @override
  String get createTemplateFriendshipLabel => '友情';

  @override
  String get createTemplateFriendshipTopic => '友だちを助けて、一緒に問題を解決するお話';

  @override
  String get createTemplateFeelingsLabel => 'きもちのケア';

  @override
  String get createTemplateFeelingsTopic => 'こわい夜に、勇気を出して恐れを乗りこえるお話';

  @override
  String get createTemplateSpaceLabel => '宇宙の冒険';

  @override
  String get createTemplateSpaceTopic => '星や惑星を探検して、すてきなものを見つけるお話';

  @override
  String get createStyleLabel => 'イラストのスタイル';

  @override
  String get createThemeLabel => 'テーマ(任意)';

  @override
  String get createThemeNone => 'なし';

  @override
  String get createCharacterLabel => '主人公キャラクター';

  @override
  String get createAddCharacter => 'キャラクターを追加';

  @override
  String get createCharacterHint => '既存のキャラクターを選ぶか、AIが新しいキャラクターを作成します';

  @override
  String get createAiCharacterTitle => 'AIが新しいキャラクターを作成';

  @override
  String get createAiCharacterDesc => 'お話に合ったキャラクターを自動で作成します';

  @override
  String get createChildProtagonistTitle => 'お子さまを主人公に';

  @override
  String get createChildProtagonistDesc => '写真または基本キャラクターで主人公を作成します';

  @override
  String get createOrSelectExisting => 'または既存のキャラクターを選択';

  @override
  String createSelectedCount(Object count) {
    return '$count人選択中(家族・友だちのお話が作れます)';
  }

  @override
  String get createAddCharacterTip => 'キャラクターを追加すると、同じキャラクターでシリーズが作れます!';

  @override
  String get createCharacterLoadError => 'キャラクターを読み込めませんでした';

  @override
  String get createRelationshipLabel => '関係（任意）';

  @override
  String get createRelationshipFriends => '友だち';

  @override
  String get createRelationshipSiblings => 'きょうだい';

  @override
  String get createRelationshipFamily => '家族';

  @override
  String get createForbiddenLabel => '入れたくない要素（任意）';

  @override
  String get createForbiddenViolence => '暴力';

  @override
  String get createForbiddenScary => 'こわい内容';

  @override
  String get createForbiddenSad => '悲しい結末';

  @override
  String get createForbiddenRude => '乱暴な言葉';

  @override
  String get createMakeButton => '絵本を作る';

  @override
  String get createPlanUpgradeTitle => 'プランのアップグレードが必要です';

  @override
  String get createCreditShortageTitle => 'クレジットが不足しています';

  @override
  String get createFailedSnack => '絵本の作成に失敗しました。しばらくしてから再試行してください。';

  @override
  String get libraryTitle => 'マイライブラリ';

  @override
  String get librarySeriesBadge => 'シリーズ';

  @override
  String get librarySeriesAddVolume => '次の巻を作る';

  @override
  String get libraryRefresh => '更新';

  @override
  String get librarySortNewest => '新しい順';

  @override
  String get librarySortOldest => '古い順';

  @override
  String get librarySortTitle => 'タイトル順';

  @override
  String get libraryStyleWatercolor => '水彩画';

  @override
  String get libraryStyleCartoon => 'カートゥーン';

  @override
  String get libraryStyle3d => '3D';

  @override
  String get libraryStylePixel => 'ピクセル';

  @override
  String get libraryStyleOilPainting => '油絵';

  @override
  String get libraryStyleClaymation => 'クレイ';

  @override
  String get libraryStyleRealistic => 'リアル';

  @override
  String get libraryAge3to5 => '3〜5歳';

  @override
  String get libraryAge5to7 => '5〜7歳';

  @override
  String get libraryAge7to9 => '7〜9歳';

  @override
  String get libraryAgeAdult => '大人';

  @override
  String get libraryRenameDialogTitle => '絵本の名前を変更';

  @override
  String get libraryRenameFieldLabel => 'タイトル';

  @override
  String get libraryRenameFieldHint => '絵本のタイトルを入力してください';

  @override
  String get libraryCancel => 'キャンセル';

  @override
  String get librarySave => '保存';

  @override
  String get libraryRenameSuccess => '絵本の名前を変更しました。';

  @override
  String get libraryDeleteDialogTitle => '絵本を削除';

  @override
  String libraryDeleteDialogContent(Object title) {
    return '「$title」を削除しますか？\n削除した絵本は復元できません。';
  }

  @override
  String get libraryDelete => '削除';

  @override
  String get libraryDeleteSuccess => '絵本を削除しました。';

  @override
  String get libraryErrorNetwork => 'インターネット接続を確認してから再試行してください。';

  @override
  String get libraryErrorGeneric => 'リクエストの処理中にエラーが発生しました。しばらくしてから再試行してください。';

  @override
  String libraryShareMessage(Object title) {
    return '📚 $title\n\nAI Story Bookで作った絵本です。\nお子さんに特別なお話を聞かせてあげましょう！';
  }

  @override
  String get libraryShareFailed => '共有に失敗しました。しばらくしてから再試行してください。';

  @override
  String get librarySortLabel => '並べ替え';

  @override
  String get libraryStyleLabel => 'スタイル';

  @override
  String get libraryAgeLabel => '年齢';

  @override
  String get libraryFilterAll => 'すべて';

  @override
  String get libraryResetFilters => 'フィルターをリセット';

  @override
  String get libraryEmptyFilterTitle => '条件に合う絵本がありません';

  @override
  String get libraryEmptyTitle => 'まだ作った絵本がありません';

  @override
  String get libraryEmptyFilterSubtitle => 'フィルターを解除して、ライブラリ全体を確認してみましょう。';

  @override
  String get libraryEmptySubtitle => '最初の絵本を作ってみましょう！';

  @override
  String get libraryCreateNew => '新しい絵本を作成';

  @override
  String get libraryLoadError => 'ライブラリを読み込めません';

  @override
  String get libraryRetry => '再試行';

  @override
  String get libraryDateToday => '今日';

  @override
  String get libraryDateYesterday => '昨日';

  @override
  String libraryDateDaysAgo(Object days) {
    return '$days日前';
  }

  @override
  String libraryDateMonthDay(Object month, Object day) {
    return '$month月$day日';
  }

  @override
  String get libraryClose => '閉じる';

  @override
  String get libraryOfflineBanner => 'オフライン状態です。最近読み込んだ絵本を表示しています。';

  @override
  String get libraryBookOptions => '絵本オプション';

  @override
  String get libraryMenuRename => '名前を変更';

  @override
  String get libraryMenuShare => '共有';

  @override
  String get libraryMenuDelete => '削除';

  @override
  String get loadingTitle => '絵本を作っています';

  @override
  String get loadingCompleted => '完成しました！';

  @override
  String get loadingErrorTitle => '問題が発生しました';

  @override
  String get loadingUnknownError => '不明なエラー';

  @override
  String get loadingRetryButton => '再試行';

  @override
  String get loadingCheckStatusButton => '状態を再確認';

  @override
  String get loadingBackToHomeButton => 'ホームに戻る';

  @override
  String get loadingStepWaiting => '待機中...';

  @override
  String get loadingStepPreparing => '準備中...';

  @override
  String get loadingStepNormalize => '入力を分析しています';

  @override
  String get loadingStepModerateInput => '安全性を確認しています';

  @override
  String get loadingStepGenerateStory => '物語を作っています';

  @override
  String get loadingStepGenerateCharacterSheet => 'キャラクターをデザインしています';

  @override
  String get loadingStepGenerateImagePrompts => '絵を準備しています';

  @override
  String get loadingStepGenerateImages => '絵を描いています';

  @override
  String get loadingStepModerateOutput => '最終チェック中です';

  @override
  String get loadingStepPackage => '仕上げをしています';

  @override
  String get loadingTip1 => 'お子さまに合った言葉と文章で物語が作られます';

  @override
  String get loadingTip2 => 'キャラクターが一貫して描かれるようAIが配慮しています';

  @override
  String get loadingTip3 => '完成した絵本はライブラリでいつでも見返せます';

  @override
  String get loadingTip4 => '気に入らないページは後で作り直せます';

  @override
  String get loadingTip5 => '同じキャラクターでシリーズ絵本も作れます';

  @override
  String get profilesTitle => '子どものプロフィール';

  @override
  String get profilesAddTooltip => 'プロフィールを追加';

  @override
  String get profilesLoadError => 'プロフィール情報を読み込めませんでした。';

  @override
  String get profilesDialogAddTitle => 'プロフィールを追加';

  @override
  String get profilesDialogEditTitle => 'プロフィールを編集';

  @override
  String get profilesNameLabel => '名前';

  @override
  String get profilesNameHint => '例: ミンジ';

  @override
  String get profilesNameRequired => '名前を入力してください。';

  @override
  String get profilesBirthYearLabel => '生年（任意）';

  @override
  String get profilesBirthMonthLabel => '月';

  @override
  String profilesYearOption(Object year) {
    return '$year年';
  }

  @override
  String profilesMonthOption(Object month) {
    return '$month月';
  }

  @override
  String profilesAgeBandAuto(Object band) {
    return '年齢層自動: $band歳';
  }

  @override
  String get profilesBirthHint => '生年月を入力すると年齢層が自動設定されます（任意）。';

  @override
  String get profilesAgeBandLabel => '年齢層';

  @override
  String get profilesAgeBand35 => '3〜5歳';

  @override
  String get profilesAgeBand57 => '5〜7歳';

  @override
  String get profilesAgeBand79 => '7〜9歳';

  @override
  String get profilesAgeBandAdult => '大人';

  @override
  String profilesAgeBandValue(Object label) {
    return '年齢層: $label';
  }

  @override
  String get profilesSetAsDefaultSwitch => 'デフォルトのプロフィールに設定';

  @override
  String get profilesCancel => 'キャンセル';

  @override
  String get profilesAddAction => '追加';

  @override
  String get profilesSaveAction => '保存';

  @override
  String get profilesCreateFailed => 'プロフィールの作成に失敗しました。しばらくしてから再試行してください。';

  @override
  String get profilesEditFailed => 'プロフィールの編集に失敗しました。';

  @override
  String get profilesSetDefaultFailed => 'デフォルトのプロフィール設定に失敗しました。';

  @override
  String get profilesDeleteTitle => 'プロフィールを削除';

  @override
  String get profilesDeleteConfirm => 'このプロフィールを削除しますか？';

  @override
  String get profilesDeleteAction => '削除';

  @override
  String get profilesDeleteFailed => 'プロフィールの削除に失敗しました。';

  @override
  String get profilesEmpty => '登録されたプロフィールがありません';

  @override
  String get profilesCreateFirst => '最初のプロフィールを作成';

  @override
  String get profilesDefaultBadge => 'デフォルト';

  @override
  String get profilesActiveBadge => '使用中';

  @override
  String get profilesMenuActivate => '使用中のプロフィールにする';

  @override
  String get profilesMenuSetDefault => 'デフォルトのプロフィールに設定';

  @override
  String get profilesMenuEdit => '編集';

  @override
  String get voiceProfilesTitle => '家族の音声';

  @override
  String get voiceProfilesAddTooltip => '音声プロフィールを追加';

  @override
  String get voiceProfilesMenuTooltip => 'メニューを開く';

  @override
  String get voiceProfilesLoadError => '家族の音声情報を読み込めませんでした。';

  @override
  String get voiceProfilesAddTitle => '音声プロフィールを追加';

  @override
  String get voiceProfilesEditTitle => '音声プロフィールを編集';

  @override
  String get voiceProfilesLabelFieldLabel => '名前・ラベル';

  @override
  String get voiceProfilesLabelFieldHint => '例: ママの音声';

  @override
  String get voiceProfilesLabelRequired => 'ラベルを入力してください。';

  @override
  String get voiceProfilesRelationshipFieldLabel => '関係';

  @override
  String get voiceProfilesRelationshipFieldHint => '例: mother, grandmother';

  @override
  String get voiceProfilesSampleUrlFieldLabel => 'サンプル音声URL';

  @override
  String get voiceProfilesSampleUrlRequired => 'サンプル音声URLを入力してください。';

  @override
  String get voiceProfilesSampleUrlInvalid => '有効なURLを入力してください。';

  @override
  String get voiceProfilesSampleUploadSuccess => '音声サンプルのアップロードが完了しました。';

  @override
  String get voiceProfilesSampleUploadError => 'サンプルのアップロードに失敗しました。再試行してください。';

  @override
  String get voiceProfilesUploading => 'アップロード中...';

  @override
  String get voiceProfilesUploadAudioButton => '音声ファイルをアップロード';

  @override
  String get voiceProfilesConsentToggle => '保護者の同意完了';

  @override
  String get voiceProfilesActiveToggle => 'アクティブ状態';

  @override
  String get voiceProfilesCancel => 'キャンセル';

  @override
  String get voiceProfilesAdd => '追加';

  @override
  String get voiceProfilesSave => '保存';

  @override
  String get voiceProfilesCreateError => '音声プロフィールの作成に失敗しました。';

  @override
  String get voiceProfilesEditError => '音声プロフィールの編集に失敗しました。';

  @override
  String get voiceProfilesRevokeError => '同意の撤回処理に失敗しました。';

  @override
  String get voiceProfilesDeleteTitle => '音声プロフィールを削除';

  @override
  String get voiceProfilesDeleteConfirm => 'この音声プロフィールを削除しますか？';

  @override
  String get voiceProfilesDelete => '削除';

  @override
  String get voiceProfilesDeleteError => '音声プロフィールの削除に失敗しました。';

  @override
  String get voiceProfilesEmpty => '登録された家族の音声がありません。\n右上の＋ボタンから追加してください。';

  @override
  String get voiceProfilesUnnamed => '名前なし';

  @override
  String get voiceProfilesMenuEdit => '編集';

  @override
  String get voiceProfilesMenuRevoke => '同意を撤回';

  @override
  String get voiceProfilesMenuDelete => '削除';

  @override
  String voiceProfilesRelationshipPrefix(Object relationship) {
    return '関係: $relationship';
  }

  @override
  String get voiceProfilesConsentDone => '同意完了';

  @override
  String get voiceProfilesConsentNeeded => '同意が必要';

  @override
  String get voiceProfilesActive => 'アクティブ';

  @override
  String get voiceProfilesInactive => '非アクティブ';

  @override
  String get podOrderTitle => '実物本の注文';

  @override
  String get podOrderBookLabel => '注文する絵本';

  @override
  String get podOrderRecipientNameLabel => '受取人の名前';

  @override
  String get podOrderRecipientNameError => '受取人の名前を入力してください。';

  @override
  String get podOrderAddressLabel => '住所';

  @override
  String get podOrderAddressError => '住所を入力してください。';

  @override
  String get podOrderPostalLabel => '郵便番号';

  @override
  String get podOrderPostalError => '郵便番号を入力してください。';

  @override
  String get podOrderCountryLabel => '国コード';

  @override
  String get podOrderCountryError => '国コードを入力してください。';

  @override
  String get podOrderPhoneLabel => '電話番号';

  @override
  String get podOrderPhoneError => '電話番号を入力してください。';

  @override
  String get podOrderQuantityLabel => '数量';

  @override
  String podOrderQuantityValue(Object count) {
    return '$count冊';
  }

  @override
  String podOrderEstimatedTotal(Object amount) {
    return '見込み $amountウォン';
  }

  @override
  String get podOrderSubmitting => '注文処理中...';

  @override
  String get podOrderSubmitButton => '注文する';

  @override
  String get podOrderSubmitSuccess => '注文を受け付けました。';

  @override
  String get podOrderSubmitError => '注文の受付に失敗しました。情報をご確認ください。';

  @override
  String get podOrderStatusError => '注文状況の取得に失敗しました。';

  @override
  String get podOrderStatusTitle => '注文状況';

  @override
  String podOrderOrderNumber(Object orderId) {
    return '注文番号: $orderId';
  }

  @override
  String podOrderProviderOrderNumber(Object providerOrderId) {
    return 'サプライヤー注文番号: $providerOrderId';
  }

  @override
  String get podOrderCopyTooltip => 'コピー';

  @override
  String get podOrderProviderOrderCopied => 'サプライヤー注文番号をコピーしました。';

  @override
  String podOrderStatusValue(Object status) {
    return '状態: $status';
  }

  @override
  String podOrderPaymentAmount(Object amount) {
    return '決済金額: $amountウォン';
  }

  @override
  String podOrderSyncValue(Object source) {
    return '同期: $source';
  }

  @override
  String podOrderTrackingNumber(Object trackingNumber) {
    return '送り状番号: $trackingNumber';
  }

  @override
  String get podOrderRefreshStatus => '状態を更新';

  @override
  String get podOrderDecreaseQuantityTooltip => '数量を減らす';

  @override
  String get podOrderIncreaseQuantityTooltip => '数量を増やす';

  @override
  String get branchStoryTitle => '分岐ストーリー';

  @override
  String get branchStoryRefreshTooltip => '更新';

  @override
  String get branchStoryLoadError => '分岐ストーリーの情報を読み込めませんでした。';

  @override
  String get branchStoryResumeStatus => '前回の続きから読書を再開しています。';

  @override
  String get branchStoryEndingReached => 'この分岐のエンディングに到着しました。';

  @override
  String get branchStoryChoiceApplied => '選択を適用しました。';

  @override
  String branchStoryEndingArrived(Object selected) {
    return 'エンディング到着: $selected';
  }

  @override
  String branchStorySelected(Object selected) {
    return '選択: $selected';
  }

  @override
  String get branchStoryChoiceFailed => '選択の適用に失敗しました。再試行してください。';

  @override
  String get branchStorySampleText1 => 'うさぎは分かれ道に立ちました。';

  @override
  String get branchStorySampleText2 => '左の道で新しい友だちに出会いました。';

  @override
  String get branchStorySampleText3 => '右の道で宝物を見つけました。';

  @override
  String get branchStorySampleOptionLeft => '左の道へ進む';

  @override
  String get branchStorySampleOptionRight => '右の道へ進む';

  @override
  String get branchStorySampleCreated => 'サンプルの分岐ストーリーを作成しました。';

  @override
  String get branchStorySampleCreateFailed => 'サンプル分岐の作成に失敗しました。';

  @override
  String branchStoryNodeLabel(Object nodeKey) {
    return 'ノード: $nodeKey';
  }

  @override
  String branchStoryPageLabel(Object pageNumber) {
    return 'ページ $pageNumber';
  }

  @override
  String get branchStoryImageSemantics => '分岐ストーリーの挿絵';

  @override
  String get branchStoryOptionsHeading => '選択肢';

  @override
  String get branchStoryNoOptions => 'これ以上の選択肢はありません。この分岐のエンディングです。';

  @override
  String get branchStoryPreviousChoice => '前の選択';

  @override
  String get branchStoryRestart => '最初から';

  @override
  String get branchStoryRetry => '再試行';

  @override
  String get branchStoryEmptyTitle => 'まだ分岐ストーリーがありません。';

  @override
  String get branchStoryEmptySubtitle =>
      'サンプル分岐を作成して、インタラクティブなストーリーをすぐに体験できます。';

  @override
  String get branchStorySampleCreating => '作成中...';

  @override
  String get branchStoryCreateSample => 'サンプル分岐を作成';

  @override
  String get pronunciationTitle => '発音練習';

  @override
  String pronunciationIntro(Object pageNumber) {
    return '絵本$pageNumberページの文章を基準に発音を評価します。';
  }

  @override
  String get pronunciationExpectedLabel => '基準の文章';

  @override
  String get pronunciationTranscriptLabel => '読んだ文章（テキスト入力）';

  @override
  String get pronunciationTranscriptHint => 'お子さまが読んだ文章を入力してください。';

  @override
  String get pronunciationEvaluating => '評価中...';

  @override
  String get pronunciationEvaluateButton => '発音を評価する';

  @override
  String get pronunciationEvaluateAudioButton => '音声ファイルで評価';

  @override
  String pronunciationScore(Object score) {
    return '発音スコア: $score点';
  }

  @override
  String get pronunciationNoFeedback => 'フィードバックはありません。';

  @override
  String get pronunciationErrorBothRequired => '基準の文章と読んだ文章の両方を入力してください。';

  @override
  String get pronunciationErrorEvaluateFailed =>
      '発音の評価に失敗しました。しばらくしてから再試行してください。';

  @override
  String get pronunciationErrorExpectedRequired => '先に基準の文章を入力してください。';

  @override
  String get pronunciationErrorAudioEvaluateFailed =>
      '音声の発音評価に失敗しました。再試行してください。';

  @override
  String get parentDashboardLoadError => 'ダッシュボードのデータを読み込めませんでした。';

  @override
  String get parentDashboardReportMonthly => '月間レポート';

  @override
  String get parentDashboardReportWeekly => '週間レポート';

  @override
  String get parentDashboardTitle => '保護者ダッシュボード';

  @override
  String get parentDashboardRefreshTooltip => '更新';

  @override
  String get parentDashboardSegmentWeekly => '週間';

  @override
  String get parentDashboardSegmentMonthly => '月間';

  @override
  String get parentDashboardThemeUnspecified => '未指定';

  @override
  String get parentDashboardMetricTotalBooksTitle => '読んだ絵本の合計';

  @override
  String parentDashboardMetricTotalBooksValue(Object count) {
    return '$count冊';
  }

  @override
  String get parentDashboardMetricTotalMinutesTitle => '合計の読書時間';

  @override
  String parentDashboardMetricTotalMinutesValue(Object minutes) {
    return '$minutes分';
  }

  @override
  String get parentDashboardMetricAvgMinutesTitle => '平均の読書時間';

  @override
  String parentDashboardMetricAvgMinutesValue(Object minutes) {
    return '$minutes分';
  }

  @override
  String get parentDashboardMetricPreferredThemeTitle => '好みのテーマ';

  @override
  String get parentDashboardLearningTitle => '学習状況';

  @override
  String parentDashboardLearningStreakLine(Object current, Object longest) {
    return '現在のストリーク $current日 ・ 最高 $longest日';
  }

  @override
  String parentDashboardLearningSessionLine(Object completed, Object total) {
    return '読了セッション $completed / 全セッション $total';
  }

  @override
  String parentDashboardLearningCompletionLine(Object rate) {
    return '完了率 $rate%';
  }

  @override
  String get parentDashboardDailyChartTitle => '日別の読書時間';

  @override
  String get settingsLoadError => '設定を読み込めませんでした。';

  @override
  String get settingsSaved => '設定を保存しました。';

  @override
  String get settingsSaveError => '設定の保存に失敗しました。しばらくしてから再試行してください。';

  @override
  String get settingsBedtimeNotificationTitle => '今日の絵本を読む時間です';

  @override
  String get settingsBedtimeNotificationBody => '寝る前に今日の絵本を一緒に読みましょう';

  @override
  String get settingsRevokeConsentTitle => '同意の撤回';

  @override
  String get settingsRevokeConsentContent =>
      '同意を撤回するとアプリの利用が制限され、データの削除を進めることができます。';

  @override
  String get settingsCancel => 'キャンセル';

  @override
  String get settingsRevoke => '撤回';

  @override
  String get settingsRevokeConsentError =>
      '撤回の処理に失敗しました。ネットワークを確認してから再試行してください。';

  @override
  String get settingsConsentRevoked => '同意が撤回されました。';

  @override
  String get settingsDeleteAllTitle => '自分のデータをすべて削除';

  @override
  String get settingsDeleteAllContent => 'この操作は取り消せません。続行しますか？';

  @override
  String get settingsContinue => '続行';

  @override
  String get settingsFinalConfirmTitle => '最終確認';

  @override
  String get settingsFinalConfirmPrompt => '削除を進めるには、下に「삭제」と入力してください。';

  @override
  String get settingsDeleteKeyword => '削除';

  @override
  String get settingsDeleteKeywordMismatch => '確認テキストが一致しません。';

  @override
  String get settingsDeleteError => 'データの削除に失敗しました。しばらくしてから再試行してください。';

  @override
  String get settingsLinkCopied => 'リンクをコピーしました。';

  @override
  String get settingsTitle => '設定';

  @override
  String get settingsSave => '保存';

  @override
  String get settingsSectionAccount => 'アカウント';

  @override
  String get settingsChildProfile => '子どものプロフィール';

  @override
  String get settingsParentDashboard => '保護者ダッシュボード';

  @override
  String get settingsParentDashboardSubtitle => '週間／月間の読書レポート';

  @override
  String get settingsFamilyVoice => '家族の音声';

  @override
  String get settingsFamilyVoiceSubtitle => '録音サンプルと同意状況の管理';

  @override
  String get settingsCreditsSubscription => 'クレジット／サブスクリプション';

  @override
  String get settingsPoliciesTitle => 'ポリシー';

  @override
  String get settingsPoliciesSubtitle => 'クレジット繰り越し・解約後の保管・印刷返金';

  @override
  String get policyCreditRolloverTitle => 'クレジットの繰り越し';

  @override
  String get policyCreditRolloverBody => '未使用のクレジットは、定期購読が有効な間、翌月へ繰り越されます。';

  @override
  String get policyBookAccessTitle => '解約後の絵本';

  @override
  String get policyBookAccessBody => '解約しても、すでに作成した絵本はそのまま閲覧・ダウンロードできます。';

  @override
  String get policyRefundTitle => '印刷の返金・再印刷';

  @override
  String get policyRefundBody => '印刷物に不良や配送中の破損があった場合、無料で再印刷または返金します。';

  @override
  String get settingsSectionApp => 'アプリ設定';

  @override
  String get settingsLanguage => '言語';

  @override
  String get settingsLanguageKorean => '한국어';

  @override
  String get settingsLanguageEnglish => 'English';

  @override
  String get settingsDarkMode => 'ダークモード';

  @override
  String get settingsDarkModeSubtitle => 'アプリ全体のテーマを暗くします。';

  @override
  String get settingsKakaoShare => 'カカオトークのカード共有';

  @override
  String get settingsKakaoShareSubtitle => '共有メニューにカカオトーク共有を表示します。';

  @override
  String get settingsSectionSleep => 'スリープモード';

  @override
  String get settingsBedtimeNotification => '就寝通知';

  @override
  String get settingsBedtime => '就寝時間';

  @override
  String settingsSleepTimer(Object minutes) {
    return 'デフォルトのスリープタイマー：$minutes分';
  }

  @override
  String settingsMinutes(Object minutes) {
    return '$minutes分';
  }

  @override
  String get settingsSectionScreenTime => '画面時間制限';

  @override
  String get settingsScreenTimeEnabled => '画面時間制限を使用';

  @override
  String settingsDailyLimit(Object minutes) {
    return '1日の制限：$minutes分';
  }

  @override
  String get settingsSectionAppInfo => 'アプリ情報';

  @override
  String get settingsAppVersion => 'アプリバージョン';

  @override
  String get settingsPrivacyPolicy => 'プライバシーポリシー';

  @override
  String get settingsTermsOfService => '利用規約';

  @override
  String get settingsSectionPrivacy => '個人情報';

  @override
  String get settingsRevokeParentalConsent => '保護者の同意を撤回';

  @override
  String get settingsDeleteAllData => '自分のデータをすべて削除';

  @override
  String get settingsDeleteAllDataSubtitle => '絵本、キャラクター、読書記録などすべてのデータが削除されます。';

  @override
  String get creditsTitle => 'クレジット';

  @override
  String get creditsRestorePurchases => '購入を復元';

  @override
  String get creditsLoadError => 'クレジット情報を読み込めませんでした。しばらくしてから再試行してください。';

  @override
  String get creditsMyCredits => 'マイクレジット';

  @override
  String creditsTotalCreated(Object count) {
    return '合計$count冊作成';
  }

  @override
  String get creditsUnit => 'クレジット';

  @override
  String get creditsBuyCredits => 'クレジットを購入';

  @override
  String get creditsBadgeCancelScheduled => '解約予定';

  @override
  String get creditsBadgeActive => '有効';

  @override
  String get creditsSubscriptionInfo => 'サブスクリプション情報';

  @override
  String get creditsNoActivePlan => '現在ご利用中のプランはありません。';

  @override
  String get creditsStartSubscription => 'サブスクリプションを開始';

  @override
  String creditsPlanSubscriptionLabel(Object planName) {
    return '$planName サブスクリプション';
  }

  @override
  String get creditsDefaultPlanName => 'ベーシック';

  @override
  String get creditsMonthlyCredits => '月間クレジット';

  @override
  String creditsCreditCount(Object count) {
    return '$count個';
  }

  @override
  String get creditsNextRenewal => '次回更新日';

  @override
  String get creditsCancelNotice => '現在の請求サイクルが終了すると、無料プランに切り替わります。';

  @override
  String get creditsCancelSubscription => 'サブスクリプションを解約';

  @override
  String get creditsPlansTitle => 'サブスクリプションプラン';

  @override
  String get creditsNoAvailablePlans => '現在利用可能なサブスクリプションプランはありません。';

  @override
  String get creditsPlanFallbackName => 'プラン';

  @override
  String get creditsCurrentPlan => '現在のプラン';

  @override
  String get creditsFree => '無料';

  @override
  String creditsPricePerMonth(Object price) {
    return '₩$price/月';
  }

  @override
  String creditsMonthlyCreatable(Object count) {
    return '月$count冊作成可能';
  }

  @override
  String get creditsSubscribe => 'サブスクライブ';

  @override
  String get creditsPackTitle => 'クレジットパック';

  @override
  String creditsPackName(Object count) {
    return '$count クレジットパック';
  }

  @override
  String get creditsPackSubtitle => '必要なときにすぐにチャージ';

  @override
  String get creditsBuy => '購入';

  @override
  String get creditsTransactionsTitle => '取引履歴';

  @override
  String get creditsTransactionFallback => '取引';

  @override
  String get creditsRestoring => '購入履歴を復元しています...';

  @override
  String get creditsRestoreFailed => '復元に失敗しました。しばらくしてから再試行してください。';

  @override
  String get creditsPaymentCancelledOrFailed => '支払いがキャンセルされたか失敗しました。';

  @override
  String get creditsAlreadyProcessed => 'この支払いはすでに処理済みです。';

  @override
  String get creditsAlreadySubscribed => 'すでに同じプランをご利用中です。';

  @override
  String get creditsVerifiedReflected => '支払いが確認され、クレジットが反映されました。';

  @override
  String get creditsVerifyFailed => '支払いの検証に失敗しました。しばらくしてから再試行してください。';

  @override
  String get creditsStoreUnavailable => 'ストア決済を利用できません。';

  @override
  String get creditsProceedStorePayment => 'ストア決済を進めてください。';

  @override
  String get creditsCannotStartStorePurchase => 'ストア購入を開始できませんでした。';

  @override
  String get creditsSubscriptionStarted => 'サブスクリプションが開始されました！';

  @override
  String get creditsSubscribeFailed => 'サブスクリプションに失敗しました。しばらくしてから再試行してください。';

  @override
  String get creditsCancelConfirmContent =>
      '本当にサブスクリプションを解約しますか？現在の期間が終了するまでは引き続きご利用いただけます。';

  @override
  String get creditsNo => 'いいえ';

  @override
  String get creditsConfirmCancel => '解約する';

  @override
  String get creditsSubscriptionCancelled => 'サブスクリプションが解約されました。';

  @override
  String get creditsCancelFailed => 'サブスクリプションの解約に失敗しました。しばらくしてから再試行してください。';

  @override
  String get charactersTitle => 'マイキャラクター';

  @override
  String get charactersAddTooltip => 'キャラクターを追加';

  @override
  String get charactersRefreshTooltip => '更新';

  @override
  String get charactersEmptyTitle => 'まだキャラクターがありません';

  @override
  String get charactersEmptySubtitle => '写真からキャラクターを作ってみましょう!';

  @override
  String get charactersEmptyCreateButton => '写真からキャラクターを作成';

  @override
  String get charactersLoadErrorTitle => 'キャラクターを読み込めません';

  @override
  String get charactersRetry => '再試行';

  @override
  String get charactersFabCreating => '作成中...';

  @override
  String get charactersFabCreate => '写真から作成';

  @override
  String get charactersOptionsTitle => '新しいキャラクターを作る';

  @override
  String get charactersOptionsSubtitle => 'キャラクターの作成方法を選んでください';

  @override
  String get charactersOptionTextTitle => '手動で入力';

  @override
  String get charactersOptionTextSubtitle => '名前・年齢・特徴だけ入力';

  @override
  String get charactersOptionCameraTitle => 'カメラで撮影';

  @override
  String get charactersOptionCameraSubtitle => '写真を分析してキャラクターを作成';

  @override
  String get charactersOptionGalleryTitle => 'ギャラリーから選択';

  @override
  String get charactersOptionGallerySubtitle => '既存の写真からキャラクターを作成';

  @override
  String get charactersOptionDrawingTitle => '子どもの絵から変換';

  @override
  String get charactersOptionDrawingSubtitle => '絵の写真をキャラクターとシートに変換';

  @override
  String charactersCreatedSnack(Object name) {
    return 'キャラクター$nameを作成しました!';
  }

  @override
  String charactersCreatedWithSheetsSnack(Object name, Object count) {
    return 'キャラクター$nameとシート$count枚を作成しました!';
  }

  @override
  String get charactersCreateFailed => 'キャラクターの作成に失敗しました。しばらくしてからもう一度お試しください。';

  @override
  String get charactersImagePickFailed => '画像を選択できません。もう一度お試しください。';

  @override
  String get charactersNameDialogTitle => 'キャラクター名';

  @override
  String get charactersNameDialogHint => 'キャラクター名を入力(任意)';

  @override
  String get charactersCancel => 'キャンセル';

  @override
  String get charactersConfirm => '確認';

  @override
  String get charactersDeleteDialogTitle => 'キャラクターを削除';

  @override
  String charactersDeleteDialogContent(Object name) {
    return 'キャラクター「$name」を削除しますか?';
  }

  @override
  String get charactersDelete => '削除';

  @override
  String get charactersDeletedSnack => 'キャラクターを削除しました。';

  @override
  String get charactersDeleteFailed => 'キャラクターの削除に失敗しました。もう一度お試しください。';

  @override
  String get charactersDefaultName => '新しいキャラクター';

  @override
  String get charactersAddCardLoading => 'キャラクターを作成中...';

  @override
  String get charactersAddCardTitle => '新しいキャラクターを追加';

  @override
  String get charactersAddCardSubtitle => '写真で自分だけのキャラクターを作りましょう';

  @override
  String get charactersDetailDescription => '説明';

  @override
  String get charactersDetailPersonality => '性格';

  @override
  String get charactersDetailAppearance => '外見';

  @override
  String get charactersDetailAge => '年齢';

  @override
  String get charactersDetailFace => '顔';

  @override
  String get charactersDetailHair => '髪';

  @override
  String get charactersDetailSkin => '肌';

  @override
  String get charactersDetailBody => '体型';

  @override
  String get charactersDetailClothing => '服装';

  @override
  String get charactersDetailTop => 'トップス';

  @override
  String get charactersDetailBottom => 'ボトムス';

  @override
  String get charactersDetailShoes => '靴';

  @override
  String get charactersDetailAccessories => 'アクセサリー';

  @override
  String get charactersDetailStyleNotes => 'スタイルノート';

  @override
  String get charactersDetailCreateBookButton => 'このキャラクターで新しい絵本を作る';

  @override
  String charactersCreatedDate(Object year, Object month, Object day) {
    return '$year年$month月$day日 作成';
  }

  @override
  String get charactersRoleChild => '子ども';

  @override
  String get charactersRoleBrother => 'お兄さん';

  @override
  String get charactersRoleSister => 'お姉さん';

  @override
  String get charactersRoleMom => 'お母さん';

  @override
  String get charactersRoleDad => 'お父さん';

  @override
  String get charactersRoleGrandma => 'おばあちゃん';

  @override
  String get charactersRoleGrandpa => 'おじいちゃん';

  @override
  String get charactersRoleFriend => '友だち';

  @override
  String get charactersRoleTeacher => '先生';

  @override
  String get charactersRolePet => 'ペット';

  @override
  String get charactersFormTitle => '新しいキャラクターを作る';

  @override
  String get charactersFormRoleLabel => '誰ですか?';

  @override
  String get charactersFormCustomRole => '手動で入力';

  @override
  String get charactersFormCustomRoleHint => '例:おじ、おば、魔法使い、妖精...';

  @override
  String get charactersFormNameLabel => '名前';

  @override
  String get charactersFormNameHint => 'キャラクター名を入力してください';

  @override
  String get charactersFormTraitsLabel => '性格・特徴';

  @override
  String get charactersFormTraitsHelper => '複数選択できます';

  @override
  String get charactersFormTraitsExtraHint => '追加の特徴を入力(任意)';

  @override
  String get charactersFormSubmit => 'キャラクターを作成';

  @override
  String get charactersFormRoleRequired => '役割を入力してください';

  @override
  String get charactersFormRoleSelect => '役割を選択してください';

  @override
  String get charactersFormNameRequired => '名前を入力してください';

  @override
  String get charactersFormTraitsRequired => '性格・特徴を選択してください';

  @override
  String get viewerBookLoadError => '絵本を読み込めませんでした';

  @override
  String get viewerGoBack => '戻る';

  @override
  String viewerSleepRemaining(Object time) {
    return 'スリープ $time';
  }

  @override
  String get viewerCompletionTitle => '読み終えましたね！';

  @override
  String viewerCompletionStreak(Object streak) {
    return '🔥 $streak日連続の読書達成！すごいですね。';
  }

  @override
  String get viewerCompletionMessage => '最後のページまで読みました。次の絵本も始めてみましょうか？';

  @override
  String get viewerCreateNextStory => '次の絵本を作る';

  @override
  String get viewerGoToLibrary => '本棚へ';

  @override
  String get viewerCover => '表紙';

  @override
  String viewerPageIndicator(Object current, Object total) {
    return '$current / $total';
  }

  @override
  String viewerLearningWordCount(Object count) {
    return '単語 $count';
  }

  @override
  String viewerLearningQuizCount(Object count) {
    return 'クイズ $count';
  }

  @override
  String viewerLearningQuestionCount(Object count) {
    return '質問 $count';
  }

  @override
  String viewerLearningBar(Object parts) {
    return '学習モード · $parts';
  }

  @override
  String get viewerCloseTooltip => '閉じる';

  @override
  String get viewerMoreOptionsTooltip => 'その他';

  @override
  String get viewerPreviousPageTooltip => '前のページ';

  @override
  String get viewerNextPageTooltip => '次のページ';

  @override
  String get viewerPlanUpgradeNeeded => 'プランのアップグレードが必要です';

  @override
  String get viewerCreditShortage => 'クレジットが足りません';

  @override
  String get viewerAudioPlayFailed => '音声の再生に失敗しました。しばらくしてから再試行してください。';

  @override
  String get viewerSleepModeEnded => 'スリープモードの時間が終了しました。';

  @override
  String get viewerFollowReadingOff => '追い読みモードをオフ';

  @override
  String get viewerFollowReadingOn => '追い読みモードをオン';

  @override
  String get viewerFollowReadingSubtitle => '音声の進行に合わせて文を強調します';

  @override
  String get viewerDualLanguageOff => '二言語表示をオフ';

  @override
  String get viewerDualLanguageOn => '二言語を同時表示';

  @override
  String get viewerDualLanguageSubtitle => '韓国語と英語を1つの画面で見られます';

  @override
  String get viewerBranchStoryTitle => '分岐ストーリーモード';

  @override
  String get viewerBranchStorySubtitle => '選択肢によって結末が変わるモード';

  @override
  String get viewerLearningModeTitle => '学習モード';

  @override
  String get viewerLearningModeSubtitle => '単語・質問・クイズ';

  @override
  String get viewerParentGuideTitle => '保護者ガイド';

  @override
  String get viewerParentGuideSubtitle => '話し合うテーマ、活動アイデア';

  @override
  String get viewerPronunciationTitle => '発音練習';

  @override
  String get viewerPronunciationSubtitle => '現在のページの文で発音を評価します';

  @override
  String get viewerRegeneratePageTitle => 'このページを作り直す';

  @override
  String get viewerSameCharacterNewStory => '同じキャラクターで新しい物語';

  @override
  String get viewerExportPdf => 'PDFで書き出す';

  @override
  String get viewerOrderPhysicalBook => '実物の本を注文';

  @override
  String get viewerOrderPhysicalBookSubtitle => 'POD注文で印刷版を受け取れます';

  @override
  String get viewerSleepModeStop => 'スリープモード終了';

  @override
  String get viewerSleepModeStart => 'スリープモード開始';

  @override
  String viewerSleepModeRemaining(Object time) {
    return '残り時間 $time';
  }

  @override
  String get viewerSleepModeDescription => '画面を暗く＋音声自動再生＋ページ自動めくり';

  @override
  String get viewerPrint => '印刷する';

  @override
  String get viewerShare => '共有する';

  @override
  String get viewerRegenerateDialogTitle => 'ページを作り直す';

  @override
  String get viewerRegenerateDialogContent => 'どの部分を作り直しますか？';

  @override
  String get viewerCancel => 'キャンセル';

  @override
  String get viewerRegenerateTextOnly => 'テキストのみ';

  @override
  String get viewerRegenerateImageOnly => '画像のみ';

  @override
  String get viewerRegenerateAll => 'すべて';

  @override
  String get viewerRegenerateNotSupported => 'この絵本はページの再生成に対応していません';

  @override
  String get viewerRegenerating => 'ページを作り直しています...';

  @override
  String get viewerRegenerateStarted => 'ページの再生成を開始しました。少々お待ちください。';

  @override
  String get viewerRegenerateFailed => '再生成に失敗しました。しばらくしてから再試行してください。';

  @override
  String get viewerPdfGenerating => 'PDFを生成中...';

  @override
  String viewerPdfSaved(Object fileName) {
    return 'PDFを保存しました: $fileName';
  }

  @override
  String get viewerPdfDownloadFailed => 'PDFのダウンロードに失敗しました。しばらくしてから再試行してください。';

  @override
  String get viewerShareLink => '共有リンク';

  @override
  String get viewerShareCopyUrl => 'URLをコピー';

  @override
  String get viewerShareMessage => 'メッセージ';

  @override
  String get viewerShareKakao => 'カカオトーク';

  @override
  String get viewerShareCover => '表紙を共有';

  @override
  String get viewerSharePdf => 'PDFを共有';

  @override
  String get viewerShareMore => 'その他';

  @override
  String viewerShareTextSimple(Object title) {
    return '$title\n\nAI Story Bookで作った絵本です！';
  }

  @override
  String get viewerCopyDone => 'コピーしました';

  @override
  String viewerShareLinkText(Object title, Object url) {
    return 'わが子が主人公の絵本「$title」📖\n$url\n\nAistorybookで作りました';
  }

  @override
  String get viewerShareLinkFailed => '共有リンクの作成に失敗しました。しばらくしてから再試行してください。';

  @override
  String viewerShareFullText(Object title) {
    return '📚 $title\n\nAI Story Bookで作った絵本です！\nお子さんに特別な物語を贈りましょう ✨';
  }

  @override
  String get viewerKakaoDescription => 'AI Story Bookで作った絵本';

  @override
  String viewerKakaoShareText(
      Object title, Object deepLink, Object fallbackUrl) {
    return '📚 $title\n\nカカオトークで絵本を共有します！\n$deepLink\n$fallbackUrl';
  }

  @override
  String viewerKakaoShareSubject(Object title) {
    return 'AI Story Book - $title';
  }

  @override
  String get viewerPrintFailed => '印刷に失敗しました。しばらくしてから再試行してください。';

  @override
  String viewerShareCoverText(Object title) {
    return '$title - 表紙画像';
  }

  @override
  String get viewerShareCoverFailed => '表紙の共有に失敗しました。しばらくしてから再試行してください。';

  @override
  String viewerSharePdfText(Object title) {
    return '$title - AI Story Bookで作った絵本';
  }

  @override
  String get viewerSharePdfFailed => 'PDFの共有に失敗しました。しばらくしてから再試行してください。';

  @override
  String viewerCoverImageSemantics(Object title) {
    return '絵本の表紙: $title';
  }

  @override
  String viewerPageImageSemantics(Object page) {
    return '$pageページの挿絵';
  }

  @override
  String get viewerLearn => '学習する';

  @override
  String get viewerPlayAudioTooltip => '音声を再生';

  @override
  String get viewerPauseAudioTooltip => '音声を一時停止';

  @override
  String get viewerLanguageToggleTooltip => '言語を切り替え';

  @override
  String get viewerLanguageKo => '한';

  @override
  String get viewerLanguageEn => 'EN';

  @override
  String get viewerTabWord => '単語';

  @override
  String get viewerTabQuestion => '質問';

  @override
  String get viewerTabQuiz => 'クイズ';

  @override
  String get viewerNoVocab => 'このページには単語学習がありません';

  @override
  String get viewerNoComprehension => 'このページには理解の質問がありません';

  @override
  String get viewerNoQuiz => 'このページにはクイズがありません';

  @override
  String viewerComprehensionQuestion(Object index, Object question) {
    return 'Q$index. $question';
  }

  @override
  String viewerComprehensionAnswer(Object answer) {
    return 'A. $answer';
  }

  @override
  String get viewerShowAnswer => '答えを見る';

  @override
  String viewerQuizQuestion(Object index, Object question) {
    return 'Q$index. $question';
  }

  @override
  String get viewerCheckAnswer => '答えを確認';

  @override
  String get viewerQuizCorrect => '正解です！';

  @override
  String get viewerQuizIncorrect => 'もう一度考えてみよう';

  @override
  String get viewerGuideSummaryTitle => '物語の要約';

  @override
  String get viewerGuideDiscussionTitle => '話し合う';

  @override
  String get viewerGuideActivitiesTitle => '一緒にやってみる';

  @override
  String get navShellHome => 'ホーム';

  @override
  String get navShellCreate => 'つくる';

  @override
  String get navShellLibrary => '本棚';

  @override
  String get navShellCharacters => 'キャラクター';

  @override
  String get creditShortageTitle => 'クレジットが足りません';

  @override
  String get creditShortageMessage => '下の方法でクレジットをチャージして、絵本づくりを続けられます。';

  @override
  String get creditShortageFreeTitle => '無料クレジットを受け取る';

  @override
  String get creditShortageFreeSubtitle => '広告視聴や招待で無料クレジット';

  @override
  String get creditShortageSubscribeTitle => '定期購入する';

  @override
  String get creditShortageSubscribeSubtitle => '月額の定期購入でたっぷり使う';

  @override
  String get creditShortagePurchaseTitle => 'クレジットを購入';

  @override
  String get creditShortagePurchaseSubtitle => '必要な分だけすぐにチャージ';

  @override
  String get creditShortageClose => '閉じる';

  @override
  String vocabGameQuestion(Object word) {
    return '「$word」の意味は?';
  }

  @override
  String get vocabGameCorrectFeedback => 'よくできました! ⭐';

  @override
  String vocabGameIncorrectFeedback(Object meaning) {
    return 'もう一度覚えましょう: $meaning';
  }

  @override
  String vocabGameChoiceLabel(Object choice) {
    return '選択肢: $choice';
  }

  @override
  String get characterSourceTitle => 'わが子を主人公に';

  @override
  String get characterSourceSubtitle => '写真で作るか、デフォルトのキャラクターを選んでください';

  @override
  String get characterSourcePhotoCamera => '写真を撮る';

  @override
  String get characterSourceGallery => 'ギャラリー';

  @override
  String get characterSourcePresetSectionLabel => '写真なしで始める · デフォルトのキャラクター';

  @override
  String get characterSourcePresetLoadError => 'デフォルトのキャラクターを読み込めませんでした。';

  @override
  String get characterSourceCreateFailed => '主人公を作れませんでした。しばらくしてから再試行してください。';

  @override
  String get characterSourcePhotoMissingId =>
      '写真から主人公を作れませんでした。しばらくしてから再試行してください。';

  @override
  String get characterSourcePhotoFailed =>
      '写真から主人公を作れませんでした。保護者の同意・権限を確認してください。';

  @override
  String get ageGateTitle => '保護者の確認';

  @override
  String get ageGateDescription => '購入画面にアクセスする前に保護者の確認が必要です。';

  @override
  String get ageGateAnswerHint => '正解を入力';

  @override
  String get ageGateCancel => 'キャンセル';

  @override
  String get ageGateWrongAnswer => '正解ではありません。';

  @override
  String get ageGateConfirm => '確認';
}
