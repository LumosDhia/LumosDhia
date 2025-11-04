menuentry 'New Kernel' {

  recordfail

  load_video

  gfxmode $linux_gfx_mode



  insmod gzio

  if [ x$grub_platform = xxen ]; then

    insmod xzio

    insmod lzopio

  fi



  insmod part_gpt

  insmod ext2

  set root='hd0,gpt3'



  if [ x$feature_platform_search_hint = xy ]; then

    search --no-floppy --fs-uuid --set=root \

      --hint-bios=hd0,gpt3 --hint-efi=hd0,gpt3 --hint-baremetal=ahci0,gpt3 \

      2b64322f-ad20-4e7e-ae53-1ffefa8bcd27

  else

    search --no-floppy --fs-uuid --set=root 2b64322f-ad20-4e7e-ae53-1ffefa8bcd27

  fi



  echo 'Loading Linux 5.19.0-051900-generic ...'

  linux /boot/vmlinuz-5.19.0-051900-generic \

    root=UUID=2b64322f-ad20-4e7e-ae53-1ffefa8bcd27 \

    ro find_preseed=/preseed.cfg auto noprompt priority=critical \

    locale=en_US quiet splash $vt_handoff



  echo 'Loading initial ramdisk ...'

  initrd /boot/initrd.img-5.19.0-051900-generic

}