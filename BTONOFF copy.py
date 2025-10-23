
#変更点 ビルドツールが確実にccacheを認識できるようにccacheを移動
ln -s /usr/bin/ccache /usr/local/bin/ccache

repo2 init -u "https://git.apn-dev.com/gerrit-hm23/honda/manifest" -b "14-8255-bsp-local" --reference=/home/workspace/work/A14_mirror

#変更点 Gitのセキュリティ警告を回避するため、異なる所有者のディレクトリを「安全」として登録
git config --global --add safe.directory /home/workspace_kf/bsp/14-8255-bsp-local

# #変更点 repo syncオプション変更 

# --no-clone-bundleと--optimized-fetchを追加 → 同期を高速化。
# --force-syncを削除 → 不要な再クローンを避けるため。
# --force-checkoutを維持 → ローカル変更を破棄し、マニフェスト通りにチェックアウト。


repo sync -c -j32 --no-tags --no-clone-bundle --optimized-fetch --force-checkout

#変更点snfをsnfrに置換。相対パスを使用し、移植性を向上。

sudo sed -i 's/\bsnf\b/snfr/g' SD-QNX4.5.6.0-CDC/buildfunc.sh

#変更点 相対パスに
sudo ln -snfr /home/workspace/work/A14_ES11_iosock_SDP QHS220

#変更点 権限変更
chmod 777 bsp/home/workspace_kf/bsp/14-8255-bsp-local


source SD-QNX4.5.6.0-CDC/buildfunc.sh
build_all_userdebug

#変更点 権限変更
chmod 777 bsp/home/workspace_kf/bsp/14-8255-bsp-local

build_META_CDC
