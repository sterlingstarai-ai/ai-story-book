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
}
