# Keep WebView callbacks and JS bridge methods
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

# RecyclerView/Annotations (if unused, safe to keep)
-keep class com.google.android.material.** { *; }

# Kotlin metadata
-keep class kotlin.Metadata { *; }